#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wangsheng.bridge.model_acceptance import run_model_bridge_soak
from wangsheng.local_runtime import assert_private_output_path, preflight_local_server
from wangsheng.providers import OpenAICompatibleToolCallingProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the v0.6 real-model headless soak.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--decision-interval-seconds", type=float, default=2.0)
    args = parser.parse_args()
    project = Path(args.project_root).resolve()
    output = assert_private_output_path(args.output_dir, project_root=project)
    preflight_local_server(base_url=args.base_url, expected_model=args.model, timeout_seconds=15.0)
    provider = OpenAICompatibleToolCallingProvider(
        base_url=args.base_url,
        model=args.model,
        api_key_env="WANGSHENG_LOCAL_API_KEY",
        timeout_seconds=60.0,
        temperature=0.0,
        top_p=1.0,
        max_tokens=256,
        max_retries=0,
        retry_backoff_seconds=0.0,
        send_parallel_tool_calls=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        provider_name="llama.cpp",
    )
    summary = run_model_bridge_soak(
        provider=provider,
        output_dir=output,
        duration_seconds=args.duration_seconds,
        decision_interval_seconds=args.decision_interval_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["all_infrastructure_gates_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
