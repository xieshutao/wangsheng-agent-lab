#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wangsheng.local_runtime import (
    TelemetryCollector,
    assert_private_output_path,
    collect_hardware_manifest,
    preflight_local_server,
    write_checksums,
)
from wangsheng.memory.model_acceptance import run_memory_model_acceptance
from wangsheng.providers import OpenAICompatibleToolCallingProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the one-shot WangSheng v0.7 P6 real-model memory acceptance."
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--scenario-dir", default="scenarios_memory_model_v070")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--server-pid", type=int)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument(
        "--extra-body-json",
        default='{"chat_template_kwargs":{"enable_thinking":false}}',
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project = Path(args.project_root).resolve()
    output = assert_private_output_path(args.output_dir, project_root=project)
    extra_body = json.loads(args.extra_body_json)
    if not isinstance(extra_body, dict):
        raise SystemExit("--extra-body-json must be a JSON object")

    provider = OpenAICompatibleToolCallingProvider(
        base_url=args.base_url,
        model=args.model,
        api_key_env="WANGSHENG_LOCAL_API_KEY",
        timeout_seconds=args.timeout,
        temperature=0.0,
        top_p=1.0,
        max_tokens=args.max_tokens,
        max_retries=0,
        retry_backoff_seconds=0.0,
        send_parallel_tool_calls=True,
        extra_body=extra_body,
        provider_name="llama.cpp",
    )
    preflight = preflight_local_server(
        base_url=args.base_url,
        expected_model=args.model,
        timeout_seconds=min(args.timeout, 15.0),
    )
    (output / "preflight.json").write_text(
        json.dumps(preflight.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "provider_config.json").write_text(
        json.dumps(provider.public_config(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "hardware_manifest.json").write_text(
        json.dumps(collect_hardware_manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "wangsheng.memory_model_formal_manifest.v1",
        "phase": "v0.7-P6",
        "scenario_dir": str((project / args.scenario_dir).resolve()),
        "formal_repeat": 1,
        "model": args.model,
        "temperature": 0.0,
        "top_p": 1.0,
        "max_retries": 0,
        "parallel_tool_calls": False,
        "thinking": False,
        "kernel_authority": "deterministic",
    }
    (output / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    telemetry = TelemetryCollector(process_pid=args.server_pid, sample_interval_seconds=0.5)
    telemetry.start()
    try:
        summary = run_memory_model_acceptance(
            scenario_dir=project / args.scenario_dir,
            output_dir=output / "acceptance",
            provider=provider,
        )
    finally:
        telemetry.stop()
        telemetry.write_csv(output / "telemetry.csv")
        (output / "telemetry_summary.json").write_text(
            json.dumps(telemetry.summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    formal = {
        "schema_version": "wangsheng.memory_model_formal_summary.v1",
        "phase": "v0.7-P6",
        "acceptance": summary,
        "telemetry": telemetry.summary(),
    }
    (output / "summary.json").write_text(
        json.dumps(formal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_checksums(output)
    print(json.dumps(formal, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
