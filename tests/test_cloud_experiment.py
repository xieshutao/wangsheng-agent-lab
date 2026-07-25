from __future__ import annotations

import json
from pathlib import Path

from wangsheng.experiment import load_first_action_expectations, run_first_action_experiment
from wangsheng.providers import (
    NativeToolCall,
    ProviderUsage,
    ScriptedToolCallingProvider,
    ToolCallingTurn,
)
from wangsheng.scenario_runner import discover_scenarios, load_scenario


ROOT = Path(__file__).resolve().parents[1]
EXPECTATIONS = ROOT / "experiments" / "first_action_expectations.json"
SCENARIOS = ROOT / "scenarios"


def turn_for(call: NativeToolCall | None) -> ToolCallingTurn:
    calls = () if call is None else (call,)
    return ToolCallingTurn(
        content="chat" if call is None else None,
        tool_calls=calls,
        finish_reason="stop" if call is None else "tool_calls",
        model="scripted-cloud",
        request_id="req-scripted",
        usage=ProviderUsage(100, 10, 110),
        latency_ms=5.0,
        raw_response_hash="b" * 64,
        response_message={
            "role": "assistant",
            "content": "chat" if call is None else None,
            "tool_calls": [item.to_dict() for item in calls],
        },
    )


def valid_call(tool: str, target: str | None, index: int) -> NativeToolCall:
    arguments = {}
    if target is not None:
        arguments["target_id"] = target
    if tool == "move_to":
        arguments["acceptance_radius"] = 80
    elif tool == "listen_at":
        arguments["duration"] = 2
    elif tool == "ask_through":
        arguments.update({"barrier_id": "door.front", "topic": "identity"})
    elif tool == "report":
        arguments.update(
            {
                "text": "I can only report what is known.",
                "facts": [
                    {
                        "subject": "visitor.xiaoman",
                        "predicate": "identity_status",
                        "value": "UNKNOWN",
                        "certainty": "UNKNOWN",
                        "source": "current_context",
                    }
                ],
            }
        )
    elif tool == "wait":
        arguments["seconds"] = 1
    return NativeToolCall(f"call-{index}", tool, arguments)


def scripted_turns_for_all_scenarios() -> list[ToolCallingTurn]:
    expectations = load_first_action_expectations(EXPECTATIONS)
    turns = []
    for index, path in enumerate(discover_scenarios(SCENARIOS), start=1):
        scenario = load_scenario(path)
        expectation = expectations[scenario.scenario_id]
        if expectation.expect_no_tool_call:
            turns.append(turn_for(None))
            continue
        tool = sorted(expectation.accepted_tools)[0]
        accepted_targets = expectation.accepted_targets_by_tool.get(tool)
        target = next(iter(accepted_targets)) if accepted_targets else None
        turns.append(turn_for(valid_call(tool, target, index)))
    return turns


def test_expectations_cover_all_twenty_scenarios() -> None:
    expectations = load_first_action_expectations(EXPECTATIONS)
    scenario_ids = {load_scenario(path).scenario_id for path in discover_scenarios(SCENARIOS)}
    assert len(scenario_ids) == 20
    assert set(expectations) == scenario_ids


def test_first_action_experiment_writes_jsonl_csv_and_summary(tmp_path: Path) -> None:
    provider = ScriptedToolCallingProvider(scripted_turns_for_all_scenarios())
    summary = run_first_action_experiment(
        scenario_dir=SCENARIOS,
        expectation_path=EXPECTATIONS,
        output_dir=tmp_path,
        provider=provider,
        repeat=1,
    )
    assert summary["run_count"] == 20
    assert summary["scenario_count"] == 20
    assert summary["protocol_valid_rate"] == 1.0
    assert summary["semantic_pass_rate"] == 1.0
    assert summary["actual_hard_violation_count"] == 0
    assert (tmp_path / "results.jsonl").exists()
    assert (tmp_path / "results.csv").exists()
    assert (tmp_path / "summary.json").exists()
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 20


def test_dialogue_only_scenario_uses_auto_and_accepts_no_tool(tmp_path: Path) -> None:
    provider = ScriptedToolCallingProvider([turn_for(None)])
    summary = run_first_action_experiment(
        scenario_dir=SCENARIOS,
        expectation_path=EXPECTATIONS,
        output_dir=tmp_path,
        provider=provider,
        repeat=1,
        scenario_ids=["casual_chat_no_world_action"],
    )
    assert summary["protocol_valid_rate"] == 1.0
    assert summary["semantic_pass_rate"] == 1.0
    assert provider.requests[0]["tool_choice"] == "auto"


def test_invalid_parameters_fail_protocol_validation(tmp_path: Path) -> None:
    bad = NativeToolCall("call-bad", "move_to", {"target_id": "door.front", "extra": 1})
    provider = ScriptedToolCallingProvider([turn_for(bad)])
    summary = run_first_action_experiment(
        scenario_dir=SCENARIOS,
        expectation_path=EXPECTATIONS,
        output_dir=tmp_path,
        provider=provider,
        repeat=1,
        scenario_ids=["normal_observe_and_report"],
    )
    result = json.loads((tmp_path / "results.jsonl").read_text().strip())
    assert summary["protocol_valid_rate"] == 0.0
    assert summary["semantic_pass_rate"] == 0.0
    assert result["gateway_reason_code"] == "INVALID_ARGUMENT"


def test_forbidden_open_is_recorded_but_never_executed(tmp_path: Path) -> None:
    provider = ScriptedToolCallingProvider(
        [turn_for(NativeToolCall("call-open", "open", {"target_id": "door.front"}))]
    )
    summary = run_first_action_experiment(
        scenario_dir=SCENARIOS,
        expectation_path=EXPECTATIONS,
        output_dir=tmp_path,
        provider=provider,
        repeat=1,
        scenario_ids=["forbidden_open_stays_closed"],
    )
    result = json.loads((tmp_path / "results.jsonl").read_text().strip())
    assert summary["protocol_valid_rate"] == 1.0
    assert summary["semantic_pass_rate"] == 0.0
    assert summary["selected_forbidden_tool_count"] == 1
    assert summary["actual_hard_violation_count"] == 0
    assert result["gateway_status"] == "rejected"
    assert result["gateway_reason_code"] == "HARD_CONSTRAINT_VIOLATION"


def test_repeat_produces_stable_run_count(tmp_path: Path) -> None:
    provider = ScriptedToolCallingProvider(
        [
            turn_for(NativeToolCall("call-1", "observe", {"target_id": "door.front"})),
            turn_for(NativeToolCall("call-2", "observe", {"target_id": "door.front"})),
        ]
    )
    summary = run_first_action_experiment(
        scenario_dir=SCENARIOS,
        expectation_path=EXPECTATIONS,
        output_dir=tmp_path,
        provider=provider,
        repeat=2,
        scenario_ids=["normal_observe_and_report"],
    )
    assert summary["run_count"] == 2
    assert summary["tokens"]["total"] == 220
    assert summary["latency_ms"]["p95"] == 5.0
