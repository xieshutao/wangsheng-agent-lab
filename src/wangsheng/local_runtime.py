from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import threading
from time import monotonic, sleep
from typing import Any, Iterable
from urllib import error, request
from urllib.parse import urlsplit, urlunsplit

from .errors import ProviderError
from .providers import ToolCallingProvider


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class LocalRuntimeError(RuntimeError):
    """Raised when a local runtime violates the frozen v0.5 contract."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class LocalServerPreflight:
    base_url: str
    model: str
    health: dict[str, Any]
    models: dict[str, Any]
    properties: dict[str, Any] | None
    tool_template_verified: bool
    checked_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.local_server_preflight.v1",
            "base_url": self.base_url,
            "model": self.model,
            "health": self.health,
            "models": self.models,
            "properties": self.properties,
            "tool_template_verified": self.tool_template_verified,
            "checked_at_utc": self.checked_at_utc,
        }


@dataclass(frozen=True, slots=True)
class ResourceSample:
    timestamp_utc: str
    monotonic_seconds: float
    process_pid: int | None
    process_rss_bytes: int | None
    system_memory_total_bytes: int | None
    system_memory_available_bytes: int | None
    gpu_index: int | None
    gpu_name: str | None
    gpu_memory_total_mib: float | None
    gpu_memory_used_mib: float | None
    gpu_utilization_percent: float | None
    gpu_temperature_c: float | None
    gpu_power_w: float | None
    process_gpu_memory_mib: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "monotonic_seconds": round(self.monotonic_seconds, 6),
            "process_pid": self.process_pid,
            "process_rss_bytes": self.process_rss_bytes,
            "system_memory_total_bytes": self.system_memory_total_bytes,
            "system_memory_available_bytes": self.system_memory_available_bytes,
            "gpu_index": self.gpu_index,
            "gpu_name": self.gpu_name,
            "gpu_memory_total_mib": self.gpu_memory_total_mib,
            "gpu_memory_used_mib": self.gpu_memory_used_mib,
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "gpu_temperature_c": self.gpu_temperature_c,
            "gpu_power_w": self.gpu_power_w,
            "process_gpu_memory_mib": self.process_gpu_memory_mib,
        }


@dataclass(slots=True)
class TelemetryCollector:
    """Best-effort, provider-neutral process/GPU sampler.

    Missing counters are recorded as null rather than invented. The collector
    uses only the Python standard library plus the vendor-provided
    ``nvidia-smi`` executable when available.
    """

    process_pid: int | None = None
    gpu_index: int = 0
    sample_interval_seconds: float = 0.5
    nvidia_smi_path: str = "nvidia-smi"
    samples: list[ResourceSample] = field(default_factory=list)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def start(self) -> None:
        if self._thread is not None:
            raise LocalRuntimeError("telemetry_already_started", "Telemetry is already running.")
        if self.sample_interval_seconds <= 0:
            raise LocalRuntimeError(
                "telemetry_invalid_interval",
                "Telemetry sample interval must be positive.",
            )
        self._stop_event.clear()
        self.samples.append(
            collect_resource_sample(
                process_pid=self.process_pid,
                gpu_index=self.gpu_index,
                nvidia_smi_path=self.nvidia_smi_path,
            )
        )
        self._thread = threading.Thread(target=self._run, name="wangsheng-telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=max(2.0, self.sample_interval_seconds * 4))
        self.samples.append(
            collect_resource_sample(
                process_pid=self.process_pid,
                gpu_index=self.gpu_index,
                nvidia_smi_path=self.nvidia_smi_path,
            )
        )
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.sample_interval_seconds):
            self.samples.append(
                collect_resource_sample(
                    process_pid=self.process_pid,
                    gpu_index=self.gpu_index,
                    nvidia_smi_path=self.nvidia_smi_path,
                )
            )

    def write_csv(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fields = list(ResourceSample.__dataclass_fields__)
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for sample in self.samples:
                writer.writerow(sample.to_dict())

    def summary(self) -> dict[str, Any]:
        rss = [item.process_rss_bytes for item in self.samples if item.process_rss_bytes is not None]
        vram = [item.gpu_memory_used_mib for item in self.samples if item.gpu_memory_used_mib is not None]
        process_vram = [
            item.process_gpu_memory_mib
            for item in self.samples
            if item.process_gpu_memory_mib is not None
        ]
        utilization = [
            item.gpu_utilization_percent
            for item in self.samples
            if item.gpu_utilization_percent is not None
        ]
        return {
            "schema_version": "wangsheng.local_telemetry_summary.v1",
            "sample_count": len(self.samples),
            "sample_interval_seconds": self.sample_interval_seconds,
            "process_pid": self.process_pid,
            "peak_process_rss_bytes": max(rss) if rss else None,
            "peak_gpu_memory_used_mib": max(vram) if vram else None,
            "peak_process_gpu_memory_mib": max(process_vram) if process_vram else None,
            "mean_gpu_utilization_percent": (
                round(sum(utilization) / len(utilization), 3) if utilization else None
            ),
            "rss_growth_ratio": _growth_ratio(rss),
            "gpu_memory_growth_ratio": _growth_ratio(vram),
        }


def assert_private_output_path(
    output_dir: str | Path,
    *,
    project_root: str | Path,
) -> Path:
    output = Path(output_dir).expanduser().resolve()
    project = Path(project_root).expanduser().resolve()
    if output == project or output.is_relative_to(project):
        raise LocalRuntimeError(
            "local_artifact_inside_repository",
            "Local model artifacts must be stored outside the public repository.",
            details={"output_dir": str(output), "project_root": str(project)},
        )
    if output.exists() and not output.is_dir():
        raise LocalRuntimeError(
            "local_output_not_directory",
            f"Output path is not a directory: {output}",
        )
    if output.exists() and any(output.iterdir()):
        raise LocalRuntimeError(
            "local_output_not_empty",
            f"Formal local output directory is not empty: {output}",
        )
    output.mkdir(parents=True, exist_ok=True)
    return output


def preflight_local_server(
    *,
    base_url: str,
    expected_model: str,
    timeout_seconds: float = 10.0,
) -> LocalServerPreflight:
    sanitized = sanitize_local_base_url(base_url)
    _require_loopback_url(sanitized)
    root_url, api_url = _split_local_urls(sanitized)
    health = _get_json(f"{root_url}/health", timeout_seconds=timeout_seconds)
    if not _health_ready(health):
        raise LocalRuntimeError(
            "local_server_not_ready",
            "The local runtime health endpoint is reachable but not ready.",
            details={"health": health},
        )
    models = _get_json(f"{api_url}/models", timeout_seconds=timeout_seconds)
    model_ids = _extract_model_ids(models)
    if expected_model not in model_ids:
        raise LocalRuntimeError(
            "local_model_alias_mismatch",
            f"Expected model alias {expected_model!r} was not returned by /v1/models.",
            details={"available_models": sorted(model_ids)},
        )
    properties: dict[str, Any] | None
    try:
        properties = _get_json(f"{root_url}/props", timeout_seconds=timeout_seconds)
    except LocalRuntimeError as exc:
        if exc.code not in {"local_http_404", "local_http_405"}:
            raise
        properties = None
    tool_template_verified = _tool_template_verified(properties)
    if not tool_template_verified:
        raise LocalRuntimeError(
            "local_tool_template_unverified",
            "The local runtime did not expose verifiable tool-aware chat-template properties.",
        )
    return LocalServerPreflight(
        base_url=sanitized,
        model=expected_model,
        health=health,
        models=models,
        properties=properties,
        tool_template_verified=tool_template_verified,
        checked_at_utc=_utc_now(),
    )


def run_synthetic_tool_contract(
    *,
    provider: ToolCallingProvider,
    output_path: str | Path,
    request_count: int = 5,
) -> dict[str, Any]:
    if request_count <= 0:
        raise ValueError("request_count must be positive")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("", encoding="utf-8")
    tool = {
        "type": "function",
        "function": {
            "name": "select_marker",
            "description": "Select the single marker named in the request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "marker_id": {
                        "type": "string",
                        "enum": ["marker.alpha"],
                    }
                },
                "required": ["marker_id"],
                "additionalProperties": False,
            },
        },
    }
    records: list[dict[str, Any]] = []
    for index in range(request_count):
        messages = [
            {
                "role": "system",
                "content": (
                    "Return exactly one native tool call. Do not answer in prose and do not "
                    "call more than one tool."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"contract": "synthetic-marker-v1", "marker_id": "marker.alpha", "nonce": index},
                    separators=(",", ":"),
                ),
            },
        ]
        try:
            turn = provider.complete_tool_call(
                messages=messages,
                tools=[tool],
                tool_choice="required",
            )
            valid = (
                len(turn.tool_calls) == 1
                and turn.tool_calls[0].name == "select_marker"
                and turn.tool_calls[0].arguments == {"marker_id": "marker.alpha"}
            )
            record = {
                "request_index": index,
                "valid": valid,
                "tool_call_count": len(turn.tool_calls),
                "tool_name": turn.tool_calls[0].name if turn.tool_calls else None,
                "arguments": turn.tool_calls[0].arguments if turn.tool_calls else None,
                "finish_reason": turn.finish_reason,
                "usage": turn.usage.to_dict(),
                "latency_ms": round(turn.latency_ms, 3),
                "provider_metrics": dict(turn.provider_metrics),
                "raw_response_hash": turn.raw_response_hash,
                "error": None,
            }
        except ProviderError as exc:
            valid = False
            record = {
                "request_index": index,
                "valid": False,
                "tool_call_count": 0,
                "tool_name": None,
                "arguments": None,
                "finish_reason": None,
                "usage": {},
                "latency_ms": None,
                "provider_metrics": {},
                "raw_response_hash": None,
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "details": dict(exc.details),
                },
            }
        records.append(record)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    passed = sum(bool(item["valid"]) for item in records)
    summary = {
        "schema_version": "wangsheng.synthetic_tool_contract.v1",
        "request_count": request_count,
        "passed_count": passed,
        "pass_rate": passed / request_count,
        "all_passed": passed == request_count,
        "output_path": str(output),
    }
    if passed != request_count:
        raise LocalRuntimeError(
            "synthetic_tool_contract_failed",
            f"Synthetic tool contract passed {passed}/{request_count}; formal run is blocked.",
            details=summary,
        )
    return summary


def collect_hardware_manifest(*, nvidia_smi_path: str = "nvidia-smi") -> dict[str, Any]:
    total, available = _system_memory()
    gpu = _query_gpu(index=0, nvidia_smi_path=nvidia_smi_path)
    return {
        "schema_version": "wangsheng.local_hardware_manifest.v1",
        "captured_at_utc": _utc_now(),
        "hostname_hash": hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "cpu": {
            "model": platform.processor() or None,
            "logical_core_count": os.cpu_count(),
            "physical_core_count": None,
        },
        "memory": {
            "total_bytes": total,
            "available_bytes": available,
        },
        "gpu": gpu,
        "nvidia_driver_version": _query_nvidia_driver(nvidia_smi_path),
    }


def collect_resource_sample(
    *,
    process_pid: int | None,
    gpu_index: int,
    nvidia_smi_path: str,
) -> ResourceSample:
    total, available = _system_memory()
    gpu = _query_gpu(index=gpu_index, nvidia_smi_path=nvidia_smi_path)
    return ResourceSample(
        timestamp_utc=_utc_now(),
        monotonic_seconds=monotonic(),
        process_pid=process_pid,
        process_rss_bytes=_process_rss(process_pid),
        system_memory_total_bytes=total,
        system_memory_available_bytes=available,
        gpu_index=_optional_int(gpu.get("index")),
        gpu_name=_optional_str(gpu.get("name")),
        gpu_memory_total_mib=_optional_float(gpu.get("memory_total_mib")),
        gpu_memory_used_mib=_optional_float(gpu.get("memory_used_mib")),
        gpu_utilization_percent=_optional_float(gpu.get("utilization_gpu_percent")),
        gpu_temperature_c=_optional_float(gpu.get("temperature_c")),
        gpu_power_w=_optional_float(gpu.get("power_w")),
        process_gpu_memory_mib=_query_process_gpu_memory(
            pid=process_pid,
            nvidia_smi_path=nvidia_smi_path,
        ),
    )


def parse_nvidia_smi_gpu_csv(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 7:
            continue
        rows.append(
            {
                "index": _parse_int(parts[0]),
                "name": parts[1] or None,
                "memory_total_mib": _parse_float(parts[2]),
                "memory_used_mib": _parse_float(parts[3]),
                "utilization_gpu_percent": _parse_float(parts[4]),
                "temperature_c": _parse_float(parts[5]),
                "power_w": _parse_float(parts[6]),
            }
        )
    return rows


def parse_nvidia_smi_process_csv(text: str) -> dict[int, float]:
    result: dict[int, float] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 2:
            continue
        pid = _parse_int(parts[0])
        memory = _parse_float(parts[1])
        if pid is not None and memory is not None:
            result[pid] = result.get(pid, 0.0) + memory
    return result


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(root: str | Path, *, output_name: str = "checksums.sha256") -> Path:
    base = Path(root)
    output = base / output_name
    lines: list[str] = []
    for path in sorted(item for item in base.rglob("*") if item.is_file() and item != output):
        relative = path.relative_to(base).as_posix()
        lines.append(f"{hash_file(path)}  {relative}")
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output


def sanitize_local_base_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    if not parts.scheme or not parts.hostname:
        raise LocalRuntimeError("local_invalid_base_url", "Local base URL must be absolute.")
    hostname = parts.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def copy_optional_artifact(source: str | Path | None, destination: str | Path) -> None:
    if source is None:
        return
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        raise LocalRuntimeError(
            "local_artifact_source_missing",
            f"Optional artifact source does not exist: {source_path}",
        )
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)


def _require_loopback_url(base_url: str) -> None:
    parts = urlsplit(base_url)
    hostname = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or hostname not in LOOPBACK_HOSTS:
        raise LocalRuntimeError(
            "local_server_not_loopback",
            "Formal local inference must bind to a loopback host only.",
            details={"base_url": base_url},
        )


def _split_local_urls(base_url: str) -> tuple[str, str]:
    parts = urlsplit(base_url)
    root = urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")
    path = parts.path.rstrip("/")
    api = f"{root}{path}" if path else f"{root}/v1"
    if not api.endswith("/v1"):
        api = f"{api}/v1"
    return root, api


def _get_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    req = request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise LocalRuntimeError(
            f"local_http_{exc.code}",
            f"Local runtime returned HTTP {exc.code} for {url}.",
        ) from exc
    except error.URLError as exc:
        raise LocalRuntimeError(
            "local_connection_error",
            f"Could not reach local runtime at {url}: {exc.reason}",
        ) from exc
    except TimeoutError as exc:
        raise LocalRuntimeError(
            "local_timeout",
            f"Local runtime request timed out: {url}",
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocalRuntimeError(
            "local_invalid_json",
            f"Local runtime returned invalid JSON for {url}.",
        ) from exc
    if not isinstance(payload, dict):
        raise LocalRuntimeError(
            "local_invalid_response",
            f"Local runtime response must be an object: {url}",
        )
    return payload


def _health_ready(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    if isinstance(status, str):
        return status.strip().lower() in {"ok", "ready", "healthy"}
    if payload.get("ready") is True:
        return True
    return False


def _tool_template_verified(properties: dict[str, Any] | None) -> bool:
    if not isinstance(properties, dict):
        return False

    def walk(value: Any, path: str = "") -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                key_path = f"{path}.{key}" if path else str(key)
                lowered = key_path.lower()
                if "tool" in lowered or "function" in lowered:
                    if item is True:
                        return True
                    if isinstance(item, str) and item.strip():
                        return True
                    if isinstance(item, (list, dict)) and item:
                        return True
                if key.lower() in {"chat_template", "chat-template"}:
                    if isinstance(item, str) and any(
                        token in item.lower() for token in ("tool", "function")
                    ):
                        return True
                if walk(item, key_path):
                    return True
        elif isinstance(value, list):
            return any(walk(item, path) for item in value)
        return False

    return walk(properties)


def _extract_model_ids(payload: dict[str, Any]) -> set[str]:
    data = payload.get("data", [])
    if not isinstance(data, list):
        return set()
    result: set[str] = set()
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result.add(item["id"])
    return result


def _system_memory() -> tuple[int | None, int | None]:
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
        except (AttributeError, OSError, ValueError):
            return None, None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        return int(page_size * total_pages), int(page_size * available_pages)
    except (AttributeError, OSError, ValueError):
        return None, None


def _process_rss(pid: int | None) -> int | None:
    if pid is None or pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            PROCESS_VM_READ = 0x0010

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
                False,
                pid,
            )
            if not handle:
                return None
            try:
                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                    handle,
                    ctypes.byref(counters),
                    counters.cb,
                )
                return int(counters.WorkingSetSize) if ok else None
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None
    status = Path(f"/proc/{pid}/status")
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                return int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _query_gpu(*, index: int, nvidia_smi_path: str) -> dict[str, Any]:
    command = [
        nvidia_smi_path,
        "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0:
        return {}
    for row in parse_nvidia_smi_gpu_csv(completed.stdout):
        if row.get("index") == index:
            return row
    return {}


def _query_process_gpu_memory(*, pid: int | None, nvidia_smi_path: str) -> float | None:
    if pid is None or pid <= 0:
        return None
    command = [
        nvidia_smi_path,
        "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return parse_nvidia_smi_process_csv(completed.stdout).get(pid)


def _query_nvidia_driver(nvidia_smi_path: str) -> str | None:
    try:
        completed = subprocess.run(
            [
                nvidia_smi_path,
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    first = completed.stdout.strip().splitlines()
    return first[0].strip() if first else None


def _growth_ratio(values: list[int] | list[float]) -> float | None:
    if len(values) < 2 or not values[0]:
        return None
    return round((values[-1] - values[0]) / values[0], 6)


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value: str) -> float | None:
    normalized = value.strip().lower()
    if normalized in {"n/a", "[not supported]", "not supported", ""}:
        return None
    try:
        return float(normalized)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
