#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from wangsheng.memory.model_acceptance import (
    build_memory_model_scenario,
    load_memory_model_scenarios,
    run_memory_model_acceptance,
)
from wangsheng.providers import (
    NativeToolCall,
    ProviderUsage,
    ScriptedToolCallingProvider,
    ToolCallingTurn,
)


def _turn(name: str, arguments: dict[str, object]) -> ToolCallingTurn:
    call = NativeToolCall("call-verifier", name, arguments)
    return ToolCallingTurn(
        content=None,
        tool_calls=(call,),
        finish_reason="tool_calls",
        model="p6-deterministic-verifier",
        request_id="req-verifier",
        usage=ProviderUsage(1, 1, 2),
        latency_ms=0.0,
        raw_response_hash="0" * 64,
        response_message={"role": "assistant", "content": None, "tool_calls": [call.to_dict()]},
        provider_name="scripted",
    )


def main() -> int:
    scenario_dir = Path("scenarios_memory_model_v070")
    scenarios = load_memory_model_scenarios(scenario_dir)
    turns = []
    expected = []
    for scenario in scenarios:
        built = build_memory_model_scenario(scenario)
        turns.append(_turn(built.expected_tool, dict(built.expected_arguments)))
        expected.append(
            {
                "scenario_id": scenario.scenario_id,
                "expected_tool": built.expected_tool,
                "expected_arguments": dict(built.expected_arguments),
                "kernel_digest": built.kernel.state_digest(),
            }
        )
    with TemporaryDirectory(prefix="wangsheng-p6-verify-") as temp:
        summary = run_memory_model_acceptance(
            scenario_dir=scenario_dir,
            output_dir=Path(temp) / "acceptance",
            provider=ScriptedToolCallingProvider(turns),
        )
    report = {
        "phase": "v0.7-P6-deterministic-preflight",
        "scenario_count": len(scenarios),
        "expected": expected,
        "summary": summary,
        "status": "PASS" if summary["status"] == "PASS" and len(scenarios) == 12 else "FAIL",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
