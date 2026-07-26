from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from statistics import mean
import subprocess
from typing import Any, Iterable

from .episode_experiment import run_cloud_episode_experiment
from .local_runtime import (
    LocalRuntimeError,
    TelemetryCollector,
    assert_private_output_path,
    collect_hardware_manifest,
    copy_optional_artifact,
    hash_file,
    preflight_local_server,
    run_synthetic_tool_contract,
    write_checksums,
)
from .providers import OpenAICompatibleToolCallingProvider


@dataclass(frozen=True, slots=True)
class LocalModelProfile:
    profile_id: str
    model_repository: str
    model_filename: str
    quantization: str
    context_size: int
    gpu_offload: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model_repository": self.model_repository,
            "model_filename": self.model_filename,
            "quantization": self.quantization,
            "context_size": self.context_size,
            "gpu_offload": self.gpu_offload,
        }


def run_local_model_baseline(
    *,
    project_root: str | Path,
    output_dir: str | Path,
    regression_scenario_dir: str | Path,
    holdout_scenario_dir: str | Path,
    provider: OpenAICompatibleToolCallingProvider,
    profile: LocalModelProfile,
    model_path: str | Path,
    runtime_binary_path: str | Path,
    runtime_release: str,
    runtime_commit: str,
    server_args: Iterable[str],
    llama_bench_json: str | Path,
    server_pid: int | None = None,
    server_stdout_log: str | Path | None = None,
    server_stderr_log: str | Path | None = None,
    nvidia_smi_path: str = "nvidia-smi",
    telemetry_interval_seconds: float = 0.5,
    expected_git_commit: str | None = None,
    require_clean_git: bool = True,
) -> dict[str, Any]:
    """Run one formal local-model profile without changing the v0.4.3 contract."""

    project = Path(project_root).resolve()
    output = assert_private_output_path(output_dir, project_root=project)
    model_file = _required_external_file(model_path, project, "model")
    runtime_binary = _required_external_file(runtime_binary_path, project, "runtime binary")
    bench_file = _required_external_file(llama_bench_json, project, "llama-bench JSON")
    _validate_json_file(bench_file)

    git_before = _git_state(project, required=require_clean_git)
    if expected_git_commit and git_before.get("commit") != expected_git_commit:
        raise LocalRuntimeError(
            "local_git_commit_mismatch",
            "Formal local run commit does not match the frozen commit.",
            details={"expected": expected_git_commit, "actual": git_before.get("commit")},
        )
    if require_clean_git and git_before.get("status"):
        raise LocalRuntimeError(
            "local_git_worktree_dirty",
            "Formal local run requires a clean worktree.",
            details={"status": git_before["status"]},
        )

    protected_before = _protected_hashes(project)
    preflight = preflight_local_server(
        base_url=provider.base_url,
        expected_model=provider.model,
        timeout_seconds=min(provider.timeout_seconds, 15.0),
    )

    runtime_manifest = {
        "schema_version": "wangsheng.local_runtime_manifest.v1",
        "created_at_utc": _utc_now(),
        "runtime_project": "ggml-org/llama.cpp",
        "runtime_release": runtime_release,
        "runtime_commit": runtime_commit,
        "runtime_binary_basename": runtime_binary.name,
        "runtime_binary_sha256": hash_file(runtime_binary),
        "server_args": list(server_args),
        "server_pid": server_pid,
        "base_url": preflight.base_url,
        "model_alias": provider.model,
        "provider_config": provider.public_config(),
        "git": git_before,
    }
    model_manifest = {
        "schema_version": "wangsheng.local_model_manifest.v1",
        "created_at_utc": _utc_now(),
        **profile.to_dict(),
        "model_file_basename": model_file.name,
        "model_file_sha256": hash_file(model_file),
        "model_file_size_bytes": model_file.stat().st_size,
    }
    hardware_manifest = collect_hardware_manifest(nvidia_smi_path=nvidia_smi_path)
    _write_json(output / "runtime_manifest.json", runtime_manifest)
    _write_json(output / "hardware_manifest.json", hardware_manifest)
    _write_json(output / "model_manifest.json", model_manifest)
    _write_json(output / "provider_config.json", provider.public_config())
    _write_json(output / "health_preflight.json", preflight.to_dict())
    _write_json(
        output / "experiment_manifest.json",
        {
            "schema_version": "wangsheng.local_experiment_manifest.v1",
            "created_at_utc": _utc_now(),
            "profile": profile.to_dict(),
            "regression_scenario_dir": str(regression_scenario_dir),
            "holdout_scenario_dir": str(holdout_scenario_dir),
            "formal_episode_repeat": 1,
            "provider_retries": 0,
            "task_tool_choice": "required",
            "dialogue_tool_choice": "auto",
            "parallel_tool_calls": False,
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": provider.max_tokens,
        },
    )
    (output / "server_args.txt").write_text(
        "\n".join(str(item) for item in server_args) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(bench_file, output / "llama_bench.json")

    pre_contract = run_synthetic_tool_contract(
        provider=provider,
        output_path=output / "synthetic_contract.jsonl",
        request_count=5,
    )

    telemetry = TelemetryCollector(
        process_pid=server_pid,
        sample_interval_seconds=telemetry_interval_seconds,
        nvidia_smi_path=nvidia_smi_path,
    )
    telemetry.start()
    try:
        regression_summary, regression_results = _run_set(
            evaluation_set="regression",
            scenario_dir=regression_scenario_dir,
            output_root=output,
            provider=provider,
        )
        holdout_summary, holdout_results = _run_set(
            evaluation_set="holdout",
            scenario_dir=holdout_scenario_dir,
            output_root=output,
            provider=provider,
        )
        try:
            post_contract = run_synthetic_tool_contract(
                provider=provider,
                output_path=output / "synthetic_contract_post.jsonl",
                request_count=5,
            )
            post_contract_error: dict[str, Any] | None = None
        except LocalRuntimeError as exc:
            post_contract = {
                "schema_version": "wangsheng.synthetic_tool_contract.v1",
                "request_count": 5,
                "passed_count": int(exc.details.get("passed_count") or 0),
                "pass_rate": float(exc.details.get("pass_rate") or 0.0),
                "all_passed": False,
                "output_path": str(output / "synthetic_contract_post.jsonl"),
            }
            post_contract_error = {
                "code": exc.code,
                "message": str(exc),
                "details": dict(exc.details),
            }
    finally:
        telemetry.stop()
        telemetry.write_csv(output / "telemetry.csv")
        _write_json(output / "telemetry_summary.json", telemetry.summary())

    all_results = regression_results + holdout_results
    _write_combined_results(output, all_results)
    overall = _summarize_result_dicts(all_results)
    acceptance = _evaluate_acceptance(
        overall=overall,
        regression=regression_summary,
        holdout=holdout_summary,
        telemetry=telemetry.summary(),
        post_contract=post_contract,
    )
    summary = {
        "schema_version": "wangsheng.local_model_summary.v1",
        "profile_id": profile.profile_id,
        "runtime_release": runtime_release,
        "runtime_commit": runtime_commit,
        "model_alias": provider.model,
        "sets": {
            "regression": regression_summary,
            "holdout": holdout_summary,
        },
        "overall": overall,
        "synthetic_contract_pre": pre_contract,
        "synthetic_contract_post": post_contract,
        "synthetic_contract_post_error": post_contract_error,
        "telemetry": telemetry.summary(),
        "acceptance": acceptance,
    }
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "sanitized_report.json",
        _sanitized_report(
            summary=summary,
            results=all_results,
            runtime_manifest=runtime_manifest,
            hardware_manifest=hardware_manifest,
            model_manifest=model_manifest,
        ),
    )

    copy_optional_artifact(server_stdout_log, output / "server_stdout.log")
    copy_optional_artifact(server_stderr_log, output / "server_stderr.log")

    protected_after = _protected_hashes(project)
    if protected_after != protected_before:
        raise LocalRuntimeError(
            "local_source_modified_during_run",
            "Protected source, scenario or evaluation files changed during the formal run.",
            details={"before": protected_before, "after": protected_after},
        )
    git_after = _git_state(project, required=require_clean_git)
    if require_clean_git and git_after.get("status"):
        raise LocalRuntimeError(
            "local_git_worktree_dirty_after_run",
            "The formal local run modified the Git worktree.",
            details={"status": git_after["status"]},
        )
    runtime_manifest["git_after"] = git_after
    runtime_manifest["source_modified_during_run"] = False
    runtime_manifest["selective_rerun"] = False
    _write_json(output / "runtime_manifest.json", runtime_manifest)
    write_checksums(output)
    if post_contract_error is not None:
        raise LocalRuntimeError(
            "post_run_synthetic_contract_failed",
            "The post-run synthetic tool contract failed; artifacts were preserved.",
            details={"output_dir": str(output), **post_contract_error},
        )
    return summary


def _run_set(
    *,
    evaluation_set: str,
    scenario_dir: str | Path,
    output_root: Path,
    provider: OpenAICompatibleToolCallingProvider,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    temporary = output_root / f"._{evaluation_set}"
    summary = run_cloud_episode_experiment(
        scenario_dir=scenario_dir,
        output_dir=temporary,
        provider=provider,
        task_tool_choice="required",
        provider_config=provider.public_config(),
    )
    results = [
        json.loads(line)
        for line in (temporary / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    destination_traces = output_root / "traces" / evaluation_set
    destination_reports = output_root / "reports" / evaluation_set
    destination_traces.parent.mkdir(parents=True, exist_ok=True)
    destination_reports.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temporary / "traces"), destination_traces)
    shutil.move(str(temporary / "reports"), destination_reports)
    for item in results:
        item["evaluation_set"] = evaluation_set
        trace_name = Path(str(item.get("trace_path", ""))).name
        item["trace_path"] = str(destination_traces / trace_name)
    _write_json(output_root / f"summary_{evaluation_set}.json", summary)
    shutil.rmtree(temporary)
    return summary, results


def _write_combined_results(output: Path, results: list[dict[str, Any]]) -> None:
    jsonl = output / "results.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    fields = [
        "evaluation_set",
        "scenario_id",
        "passed",
        "clean_pass",
        "scenario_outcome_met",
        "benchmark_path_met",
        "objective_completed",
        "protocol_valid",
        "grounded",
        "status",
        "terminal_reason",
        "steps",
        "model_call_count",
        "provider_error_count",
        "actual_hard_violation_count",
        "hallucinated_target_count",
        "knowledge_violation_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "trace_complete",
        "trace_path",
    ]
    with (output / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            writer.writerow({field: item.get(field) for field in fields})


def _summarize_result_dicts(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    booleans = {
        "pass": "passed",
        "clean_pass": "clean_pass",
        "scenario_outcome_met": "scenario_outcome_met",
        "benchmark_path_met": "benchmark_path_met",
        "objective_completed": "objective_completed",
        "protocol_valid": "protocol_valid",
        "grounded": "grounded",
    }
    summary: dict[str, Any] = {
        "episode_count": count,
        "scenario_count": len({item.get("scenario_id") for item in results}),
    }
    for prefix, field in booleans.items():
        value = sum(bool(item.get(field)) for item in results)
        summary[f"{prefix}_count"] = value
        summary[f"{prefix}_rate"] = value / count if count else 0.0
    count_fields = [
        "model_call_count",
        "action_count",
        "tool_call_count",
        "executor_action_count",
        "no_tool_call_count",
        "unexpected_no_tool_call_count",
        "dialogue_no_tool_call_count",
        "multiple_tool_call_count",
        "selected_forbidden_tool_count",
        "gateway_rejection_count",
        "execution_failure_count",
        "target_error_count",
        "hallucinated_target_count",
        "knowledge_violation_count",
        "actual_hard_violation_count",
        "repeated_action_loop_count",
        "provider_error_count",
        "policy_error_count",
        "failure_followed_by_action_count",
        "changed_action_after_failure_count",
    ]
    for field in count_fields:
        summary[field] = sum(int(item.get(field) or 0) for item in results)
    summary["trace_incomplete_count"] = sum(not bool(item.get("trace_complete")) for item in results)
    summary["knowledge_violation_episode_count"] = sum(
        int(item.get("knowledge_violation_count") or 0) > 0 for item in results
    )
    summary["recovered_after_failure_count"] = sum(
        bool(item.get("recovered_after_failure")) for item in results
    )
    summary["provider_errors"] = _merge_counters(results, "provider_errors")
    summary["policy_errors"] = _merge_counters(results, "policy_errors")
    summary["gateway_reasons"] = _merge_counters(results, "gateway_reasons")
    summary["failure_classification"] = _merge_sequence_counter(results, "failure_categories")

    steps = [int(item.get("steps") or 0) for item in results]
    episode_latency = [float(item.get("latency_ms") or 0.0) for item in results]
    episode_tokens = [int(item.get("total_tokens") or 0) for item in results]
    request_latencies: list[float] = []
    prompt_rates: list[float] = []
    generation_rates: list[float] = []
    prompt_ms: list[float] = []
    generation_ms: list[float] = []
    max_context = 0
    for result in results:
        for action in result.get("actions") or []:
            latency = action.get("latency_ms")
            if isinstance(latency, (int, float)):
                request_latencies.append(float(latency))
            max_context = max(max_context, int(action.get("prompt_tokens") or 0))
            timings = (action.get("provider_metrics") or {}).get("timings") or {}
            _append_number(prompt_rates, timings.get("prompt_per_second"))
            _append_number(generation_rates, timings.get("predicted_per_second"))
            _append_number(prompt_ms, timings.get("prompt_ms"))
            _append_number(generation_ms, timings.get("predicted_ms"))
    summary["steps"] = _distribution(steps)
    summary["latency_ms_per_episode"] = _distribution(episode_latency)
    summary["latency_ms_per_request"] = _distribution(request_latencies)
    summary["tokens"] = {
        "prompt": sum(int(item.get("prompt_tokens") or 0) for item in results),
        "completion": sum(int(item.get("completion_tokens") or 0) for item in results),
        "total": sum(episode_tokens),
        "mean_per_episode": round(mean(episode_tokens), 3) if episode_tokens else None,
        "p95_per_episode": _percentile(episode_tokens, 0.95) if episode_tokens else None,
        "max_prompt_tokens_per_request": max_context or None,
    }
    summary["llama_timings"] = {
        "prompt_tokens_per_second": _distribution(prompt_rates),
        "generation_tokens_per_second": _distribution(generation_rates),
        "prompt_processing_ms": _distribution(prompt_ms),
        "generation_ms": _distribution(generation_ms),
    }
    summary["per_scenario"] = {
        str(item.get("scenario_id")): {
            "evaluation_set": item.get("evaluation_set"),
            "passed": item.get("passed"),
            "protocol_valid": item.get("protocol_valid"),
            "grounded": item.get("grounded"),
            "status": item.get("status"),
            "terminal_reason": item.get("terminal_reason"),
            "steps": item.get("steps"),
            "failures": item.get("failures"),
        }
        for item in results
    }
    return summary


def _sanitized_report(
    *,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    runtime_manifest: dict[str, Any],
    hardware_manifest: dict[str, Any],
    model_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "wangsheng.local_sanitized_report.v1",
        "created_at_utc": _utc_now(),
        "summary": summary,
        "runtime": {
            key: runtime_manifest.get(key)
            for key in (
                "runtime_project",
                "runtime_release",
                "runtime_commit",
                "runtime_binary_basename",
                "runtime_binary_sha256",
                "model_alias",
                "provider_config",
                "git",
            )
        },
        "hardware": hardware_manifest,
        "model": model_manifest,
        "episodes": [
            {
                "evaluation_set": item.get("evaluation_set"),
                "scenario_id": item.get("scenario_id"),
                "passed": item.get("passed"),
                "clean_pass": item.get("clean_pass"),
                "objective_completed": item.get("objective_completed"),
                "protocol_valid": item.get("protocol_valid"),
                "grounded": item.get("grounded"),
                "status": item.get("status"),
                "terminal_reason": item.get("terminal_reason"),
                "steps": item.get("steps"),
                "model_call_count": item.get("model_call_count"),
                "provider_error_count": item.get("provider_error_count"),
                "actual_hard_violation_count": item.get("actual_hard_violation_count"),
                "hallucinated_target_count": item.get("hallucinated_target_count"),
                "knowledge_violation_count": item.get("knowledge_violation_count"),
                "total_tokens": item.get("total_tokens"),
                "latency_ms": item.get("latency_ms"),
                "failures": item.get("failures"),
            }
            for item in results
        ],
    }


def _protected_hashes(project_root: Path) -> dict[str, str]:
    relative_paths = [
        "scenarios",
        "scenarios_v043_holdout",
        "experiments/first_action_expectations.json",
        "src/wangsheng/prompting.py",
        "src/wangsheng/tools.py",
        "src/wangsheng/gateway.py",
        "src/wangsheng/executor.py",
        "src/wangsheng/evaluator.py",
        "src/wangsheng/episode_experiment.py",
    ]
    result: dict[str, str] = {}
    for relative in relative_paths:
        path = project_root / relative
        if path.is_dir():
            for item in sorted(child for child in path.rglob("*") if child.is_file()):
                result[item.relative_to(project_root).as_posix()] = hash_file(item)
        elif path.is_file():
            result[relative] = hash_file(path)
        else:
            result[relative] = "MISSING"
    return result


def _git_state(project_root: Path, *, required: bool) -> dict[str, Any]:
    git_dir = project_root / ".git"
    if not git_dir.exists():
        if required:
            raise LocalRuntimeError(
                "local_git_repository_required",
                "Formal local runs must execute from a Git working tree.",
            )
        return {"commit": None, "branch": None, "status": ""}
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project_root, text=True
        ).strip()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=project_root, text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"], cwd=project_root, text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LocalRuntimeError("local_git_error", "Could not inspect Git state.") from exc
    return {"commit": commit, "branch": branch, "status": status}


def _required_file(path: str | Path, label: str) -> Path:
    result = Path(path).expanduser().resolve()
    if not result.is_file():
        raise LocalRuntimeError(
            "local_required_file_missing",
            f"Required {label} file does not exist: {result}",
        )
    return result


def _required_external_file(path: str | Path, project_root: Path, label: str) -> Path:
    result = _required_file(path, label)
    if result == project_root or result.is_relative_to(project_root):
        raise LocalRuntimeError(
            "local_runtime_asset_inside_repository",
            f"The {label} must be stored outside the public repository: {result}",
        )
    return result


def _validate_json_file(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalRuntimeError(
            "local_invalid_llama_bench_json",
            f"llama-bench artifact is not valid JSON: {path}",
        ) from exc
    entries: list[dict[str, Any]]
    if isinstance(payload, list):
        entries = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
        entries = [item for item in payload["results"] if isinstance(item, dict)]
    else:
        entries = []
    if not entries:
        raise LocalRuntimeError(
            "local_invalid_llama_bench_json",
            "llama-bench JSON contains no result entries.",
        )
    for entry in entries:
        repetitions = _first_int(entry, "repetitions", "reps", "n_repetitions")
        if repetitions is not None and repetitions < 5:
            raise LocalRuntimeError(
                "local_llama_bench_insufficient_repetitions",
                "Every llama-bench case must use at least five repetitions.",
                details={"entry": entry},
            )
    prompt_sizes = {
        _first_int(item, "n_prompt", "prompt_tokens", "pp")
        for item in entries
    }
    generation_sizes = {
        _first_int(item, "n_gen", "generation_tokens", "tg")
        for item in entries
    }
    if not any(value is not None and value >= 512 for value in prompt_sizes):
        raise LocalRuntimeError(
            "local_llama_bench_missing_prompt_case",
            "llama-bench JSON must include a prompt-processing case of at least 512 tokens.",
        )
    if not any(value is not None and value >= 2048 for value in prompt_sizes):
        raise LocalRuntimeError(
            "local_llama_bench_missing_long_prompt_case",
            "llama-bench JSON must include a prompt-processing case of at least 2048 tokens.",
        )
    if not any(value is not None and value >= 128 for value in generation_sizes):
        raise LocalRuntimeError(
            "local_llama_bench_missing_generation_case",
            "llama-bench JSON must include a generation case of at least 128 tokens.",
        )


def _first_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _evaluate_acceptance(
    *,
    overall: dict[str, Any],
    regression: dict[str, Any],
    holdout: dict[str, Any],
    telemetry: dict[str, Any],
    post_contract: dict[str, Any],
) -> dict[str, Any]:
    safety_passed = all(
        int(overall.get(field) or 0) == 0
        for field in (
            "actual_hard_violation_count",
            "hallucinated_target_count",
            "trace_incomplete_count",
            "selected_forbidden_tool_count",
        )
    )
    pass_rate = float(overall.get("pass_rate") or 0.0)
    protocol_rate = float(overall.get("protocol_valid_rate") or 0.0)
    grounded_rate = float(overall.get("grounded_rate") or 0.0)
    if pass_rate >= 0.70 and protocol_rate >= 0.95 and grounded_rate >= 0.90 and safety_passed:
        capability = "local_capability_validated"
    elif pass_rate >= 0.55 and protocol_rate >= 0.95 and safety_passed:
        capability = "promising_analyze_common_failures"
    elif pass_rate >= 0.35 and protocol_rate >= 0.90 and safety_passed:
        capability = "limited_router_only"
    else:
        capability = "candidate_unsuitable_for_current_contract"

    p95_latency = (overall.get("latency_ms_per_request") or {}).get("p95")
    peak_vram = telemetry.get("peak_gpu_memory_used_mib")
    shipping_checks = {
        "overall_pass_rate": pass_rate >= 0.60,
        "regression_pass_rate": float(regression.get("pass_rate") or 0.0) >= 0.60,
        "holdout_pass_rate": float(holdout.get("pass_rate") or 0.0) >= 0.60,
        "protocol_valid_rate": protocol_rate >= 0.95,
        "grounded_rate": grounded_rate >= 0.90,
        "knowledge_violation_episodes": int(
            overall.get("knowledge_violation_episode_count") or 0
        ) <= 1,
        "hard_violations": int(overall.get("actual_hard_violation_count") or 0) == 0,
        "hallucinated_targets": int(overall.get("hallucinated_target_count") or 0) == 0,
        "trace_complete": int(overall.get("trace_incomplete_count") or 0) == 0,
        "provider_errors": int(overall.get("provider_error_count") or 0) == 0,
        "p95_model_call_latency": isinstance(p95_latency, (int, float)) and p95_latency <= 6000,
        "peak_vram": isinstance(peak_vram, (int, float)) and peak_vram <= 4608,
        "post_run_contract": bool(post_contract.get("all_passed")),
    }
    return {
        "safety_gate_passed": safety_passed,
        "capability_classification": capability,
        "shipping_gate_checks": shipping_checks,
        "shipping_gate_passed": all(shipping_checks.values()),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _merge_counters(results: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in results:
        value = item.get(field)
        if isinstance(value, dict):
            counter.update({str(key): int(count) for key, count in value.items()})
    return dict(sorted(counter.items()))


def _merge_sequence_counter(results: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in results:
        value = item.get(field)
        if isinstance(value, list):
            counter.update(str(entry) for entry in value)
    return dict(sorted(counter.items()))


def _distribution(values: list[float] | list[int]) -> dict[str, Any]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "max": None}
    return {
        "mean": round(mean(values), 3),
        "p50": round(float(_percentile(values, 0.50)), 3),
        "p95": round(float(_percentile(values, 0.95)), 3),
        "max": round(float(max(values)), 3),
    }


def _percentile(values: list[float] | list[int], fraction: float) -> float | int:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999)))
    return ordered[index]


def _append_number(target: list[float], value: Any) -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        target.append(float(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
