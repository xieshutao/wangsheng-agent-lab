from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Iterator

import pytest

from wangsheng.cli import build_parser
from wangsheng.local_experiment import (
    LocalModelProfile,
    _summarize_result_dicts,
    run_local_model_baseline,
)
from wangsheng.local_runtime import (
    LocalRuntimeError,
    ResourceSample,
    TelemetryCollector,
    assert_private_output_path,
    parse_nvidia_smi_gpu_csv,
    parse_nvidia_smi_process_csv,
    preflight_local_server,
    run_synthetic_tool_contract,
)
from wangsheng.providers import OpenAICompatibleToolCallingProvider


class LocalFakeHandler(BaseHTTPRequestHandler):
    post_count = 0
    model_alias = "qwen-local"

    def log_message(self, format, *args):  # noqa: A003
        del format, args

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": self.model_alias}]})
            return
        if self.path == "/props":
            self._json(
                200,
                {
                    "chat_template": "{% if tools %}tool_calls function{% endif %}",
                    "chat_template_caps": {"supports_tool_calls": True},
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        LocalFakeHandler.post_count += 1
        assert payload["tool_choice"] == "required"
        assert payload["parallel_tool_calls"] is False
        response = {
            "id": f"local-{LocalFakeHandler.post_count}",
            "model": self.model_alias,
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call-{LocalFakeHandler.post_count}",
                                "type": "function",
                                "function": {
                                    "name": "select_marker",
                                    "arguments": '{"marker_id":"marker.alpha"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            "timings": {
                "prompt_n": 20,
                "prompt_ms": 10.0,
                "prompt_per_second": 2000.0,
                "predicted_n": 5,
                "predicted_ms": 25.0,
                "predicted_per_second": 200.0,
            },
        }
        self._json(200, response)

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@contextmanager
def fake_server() -> Iterator[str]:
    LocalFakeHandler.post_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalFakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def local_provider(base_url: str) -> OpenAICompatibleToolCallingProvider:
    return OpenAICompatibleToolCallingProvider(
        base_url=base_url,
        model="qwen-local",
        max_retries=0,
        send_parallel_tool_calls=True,
        provider_name="llama.cpp",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def test_local_preflight_requires_loopback() -> None:
    with pytest.raises(LocalRuntimeError) as exc:
        preflight_local_server(base_url="http://192.168.1.5:8080/v1", expected_model="x")
    assert exc.value.code == "local_server_not_loopback"


def test_local_preflight_verifies_model_and_tool_template() -> None:
    with fake_server() as base_url:
        result = preflight_local_server(base_url=base_url, expected_model="qwen-local")
    assert result.tool_template_verified is True
    assert result.model == "qwen-local"
    assert result.health["status"] == "ok"


def test_local_preflight_rejects_wrong_model_alias() -> None:
    with fake_server() as base_url:
        with pytest.raises(LocalRuntimeError) as exc:
            preflight_local_server(base_url=base_url, expected_model="wrong")
    assert exc.value.code == "local_model_alias_mismatch"


def test_synthetic_contract_is_five_of_five(tmp_path: Path) -> None:
    with fake_server() as base_url:
        summary = run_synthetic_tool_contract(
            provider=local_provider(base_url),
            output_path=tmp_path / "synthetic.jsonl",
        )
    assert summary["all_passed"] is True
    assert summary["passed_count"] == 5
    assert LocalFakeHandler.post_count == 5
    records = (tmp_path / "synthetic.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 5
    assert json.loads(records[0])["provider_metrics"]["timings"]["prompt_n"] == 20


def test_private_output_rejects_repository_child(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    with pytest.raises(LocalRuntimeError) as exc:
        assert_private_output_path(project / "artifacts", project_root=project)
    assert exc.value.code == "local_artifact_inside_repository"


def test_nvidia_smi_csv_parsers() -> None:
    rows = parse_nvidia_smi_gpu_csv(
        "0, NVIDIA GeForce RTX 4060 Laptop GPU, 8192, 4321, 77, 71, 88.5\n"
    )
    assert rows[0]["memory_used_mib"] == 4321.0
    assert rows[0]["temperature_c"] == 71.0
    assert parse_nvidia_smi_process_csv("1234, 3000\n1234, 100\n") == {1234: 3100.0}


def test_telemetry_summary_reports_peak_and_growth() -> None:
    collector = TelemetryCollector(process_pid=42)
    collector.samples = [
        ResourceSample("a", 1.0, 42, 100, 1000, 500, 0, "gpu", 8000, 2000, 10, 50, 30, 1800),
        ResourceSample("b", 2.0, 42, 125, 1000, 450, 0, "gpu", 8000, 2200, 20, 55, 40, 2000),
    ]
    summary = collector.summary()
    assert summary["peak_process_rss_bytes"] == 125
    assert summary["peak_gpu_memory_used_mib"] == 2200
    assert summary["rss_growth_ratio"] == 0.25


def test_local_cli_freezes_no_retries_and_local_defaults() -> None:
    args = build_parser().parse_args(
        [
            "run-local-episodes",
            "--model",
            "qwen-local",
            "--output-dir",
            "/tmp/local-run",
            "--profile-id",
            "profile-a",
            "--model-repository",
            "Qwen/Qwen3-8B-GGUF",
            "--model-path",
            "/tmp/model.gguf",
            "--quantization",
            "Q4_K_M",
            "--runtime-binary",
            "/tmp/llama-server.exe",
            "--llama-bench-json",
            "/tmp/bench.json",
        ]
    )
    assert args.base_url == "http://127.0.0.1:8080/v1"
    assert args.context_size == 8192
    assert json.loads(args.extra_body_json)["chat_template_kwargs"]["enable_thinking"] is False


def test_local_summary_splits_behavior_and_llama_timings() -> None:
    results = [
        {
            "scenario_id": "a",
            "evaluation_set": "regression",
            "passed": True,
            "clean_pass": True,
            "scenario_outcome_met": True,
            "benchmark_path_met": True,
            "objective_completed": True,
            "protocol_valid": True,
            "grounded": True,
            "trace_complete": True,
            "steps": 2,
            "latency_ms": 100,
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "total_tokens": 25,
            "actions": [
                {
                    "latency_ms": 50,
                    "prompt_tokens": 20,
                    "provider_metrics": {
                        "timings": {
                            "prompt_per_second": 1000,
                            "predicted_per_second": 50,
                        }
                    },
                }
            ],
        },
        {
            "scenario_id": "b",
            "evaluation_set": "holdout",
            "passed": False,
            "clean_pass": False,
            "scenario_outcome_met": False,
            "benchmark_path_met": False,
            "objective_completed": False,
            "protocol_valid": True,
            "grounded": True,
            "trace_complete": True,
            "steps": 3,
            "latency_ms": 200,
            "prompt_tokens": 30,
            "completion_tokens": 5,
            "total_tokens": 35,
            "actions": [],
        },
    ]
    summary = _summarize_result_dicts(results)
    assert summary["pass_rate"] == 0.5
    assert summary["protocol_valid_rate"] == 1.0
    assert summary["tokens"]["total"] == 60
    assert summary["llama_timings"]["generation_tokens_per_second"]["mean"] == 50.0


def test_formal_local_orchestration_uses_fake_server_and_private_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    model = tmp_path / "model.gguf"
    runtime = tmp_path / "llama-server"
    bench = tmp_path / "bench.json"
    model.write_bytes(b"model")
    runtime.write_bytes(b"runtime")
    bench.write_text(
        json.dumps(
            [
                {"n_prompt": 512, "n_gen": 0, "repetitions": 5},
                {"n_prompt": 2048, "n_gen": 0, "repetitions": 5},
                {"n_prompt": 0, "n_gen": 128, "repetitions": 5},
            ]
        ),
        encoding="utf-8",
    )

    def fake_experiment(*, scenario_dir, output_dir, provider, **kwargs):
        del provider, kwargs
        target = Path(output_dir)
        (target / "traces").mkdir(parents=True)
        (target / "reports").mkdir(parents=True)
        scenario_id = "regression-case" if "regression" in str(scenario_dir) else "holdout-case"
        (target / "traces" / f"{scenario_id}.jsonl").write_text("{}\n", encoding="utf-8")
        (target / "reports" / f"{scenario_id}.json").write_text("{}", encoding="utf-8")
        result = {
            "scenario_id": scenario_id,
            "passed": True,
            "clean_pass": True,
            "scenario_outcome_met": True,
            "benchmark_path_met": True,
            "objective_completed": True,
            "protocol_valid": True,
            "grounded": True,
            "status": "completed",
            "terminal_reason": "OBJECTIVE_COMPLETED",
            "steps": 1,
            "model_call_count": 1,
            "action_count": 1,
            "tool_call_count": 1,
            "executor_action_count": 1,
            "provider_error_count": 0,
            "actual_hard_violation_count": 0,
            "hallucinated_target_count": 0,
            "knowledge_violation_count": 0,
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "total_tokens": 25,
            "latency_ms": 50,
            "trace_complete": True,
            "trace_path": str(target / "traces" / f"{scenario_id}.jsonl"),
            "actions": [],
            "failure_categories": [],
            "failures": [],
        }
        (target / "results.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
        (target / "results.csv").write_text("scenario_id\n", encoding="utf-8")
        (target / "provider_config.json").write_text("{}", encoding="utf-8")
        (target / "experiment_manifest.json").write_text("{}", encoding="utf-8")
        summary = {"episode_count": 1, "scenario_count": 1, "pass_count": 1, "pass_rate": 1.0}
        (target / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary

    monkeypatch.setattr("wangsheng.local_experiment.run_cloud_episode_experiment", fake_experiment)
    monkeypatch.setattr("wangsheng.local_experiment.collect_hardware_manifest", lambda **kwargs: {})
    monkeypatch.setattr(
        "wangsheng.local_runtime.collect_resource_sample",
        lambda **kwargs: ResourceSample("a", 1.0, None, None, None, None, None, None, None, None, None, None, None, None),
    )

    with fake_server() as base_url:
        summary = run_local_model_baseline(
            project_root=project,
            output_dir=tmp_path / "private-output",
            regression_scenario_dir="regression",
            holdout_scenario_dir="holdout",
            provider=local_provider(base_url),
            profile=LocalModelProfile("profile-a", "repo", model.name, "Q4_K_M", 8192, "full"),
            model_path=model,
            runtime_binary_path=runtime,
            runtime_release="b9637",
            runtime_commit="aedb2a5",
            server_args=["--ctx-size", "8192"],
            llama_bench_json=bench,
            telemetry_interval_seconds=10,
            require_clean_git=False,
        )
    output = tmp_path / "private-output"
    assert summary["overall"]["pass_count"] == 2
    assert (output / "checksums.sha256").exists()
    assert (output / "traces" / "regression" / "regression-case.jsonl").exists()
    assert (output / "traces" / "holdout" / "holdout-case.jsonl").exists()
    assert LocalFakeHandler.post_count == 10
