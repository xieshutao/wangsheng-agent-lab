from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

import pytest

from wangsheng.cli import build_parser
from wangsheng.episode_experiment import run_cloud_episode_experiment
from wangsheng.errors import ProviderError
from wangsheng.providers import (
    NativeToolCall,
    ProviderUsage,
    ToolCallingTurn,
)
from wangsheng.scenario_runner import discover_scenarios, load_scenario


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"


class ScenarioToolProvider:
    def __init__(self) -> None:
        self.definitions = {
            definition.scenario_id: definition
            for definition in (
                load_scenario(path) for path in discover_scenarios(SCENARIOS)
            )
        }
        self.indices: dict[str, int] = defaultdict(int)
        self.requests: list[dict[str, Any]] = []

    def complete_tool_call(self, *, messages, tools, tool_choice=None):
        user_payload = json.loads(messages[-1]["content"])
        scenario_id = user_payload["task"]["task_id"]
        definition = self.definitions[scenario_id]
        self.requests.append(
            {
                "scenario_id": scenario_id,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        if definition.mode == "dialogue_only":
            return make_turn(scenario_id, self.indices[scenario_id], None)
        index = self.indices[scenario_id]
        self.indices[scenario_id] += 1
        if index >= len(definition.actions):
            raise ProviderError(
                "provider_exhausted",
                f"No scripted action remains for {scenario_id} at {index}.",
            )
        return make_turn(scenario_id, index, definition.actions[index])


class OneTurnProvider:
    def __init__(self, turn: ToolCallingTurn) -> None:
        self.turn = turn
        self.requests: list[dict[str, Any]] = []

    def complete_tool_call(self, *, messages, tools, tool_choice=None):
        self.requests.append(
            {"messages": messages, "tools": tools, "tool_choice": tool_choice}
        )
        return self.turn


class FailingProvider:
    def complete_tool_call(self, *, messages, tools, tool_choice=None):
        del messages, tools, tool_choice
        raise ProviderError("provider_timeout", "formal request timed out")


def make_turn(scenario_id: str, index: int, action) -> ToolCallingTurn:
    if action is None:
        calls = ()
        content = "It is quiet tonight."
    else:
        parameters = canonical_to_model_visible(dict(action.parameters))
        if action.target is not None:
            parameters["target_id"] = alias(action.target)
        call = NativeToolCall(
            call_id=f"call-{scenario_id}-{index}",
            name=action.name,
            arguments=parameters,
        )
        calls = (call,)
        content = None
    return ToolCallingTurn(
        content=content,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        model="scripted-cloud-episode",
        request_id=f"req-{scenario_id}-{index}",
        usage=ProviderUsage(100, 10, 110),
        latency_ms=5.0,
        raw_response_hash=(f"{index:x}" * 64)[:64],
        response_message={
            "role": "assistant",
            "content": content,
            "tool_calls": [call.to_dict() for call in calls],
        },
    )


def alias(value: str) -> str:
    return "visitor.front_001" if value == "visitor.xiaoman" else value


def canonical_to_model_visible(value: Any) -> Any:
    if isinstance(value, str):
        return alias(value)
    if isinstance(value, list):
        return [canonical_to_model_visible(item) for item in value]
    if isinstance(value, dict):
        return {key: canonical_to_model_visible(item) for key, item in value.items()}
    return value


def test_cloud_episode_runner_executes_all_twenty_with_native_tool_fixtures(
    tmp_path: Path,
) -> None:
    provider = ScenarioToolProvider()
    summary = run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=provider,
        provider_config={"model": "scripted-cloud-episode"},
    )
    assert summary["episode_count"] == 20
    assert summary["scenario_count"] == 20
    assert summary["pass_count"] == 20
    assert summary["pass_rate"] == 1.0
    assert summary["benchmark_path_met_count"] == 20
    assert summary["protocol_valid_rate"] == 1.0
    assert summary["actual_hard_violation_count"] == 0
    assert summary["trace_incomplete_count"] == 0
    assert summary["provider_error_count"] == 0
    assert summary["model_call_count"] > 20
    assert summary["grounded_count"] < 20  # fixtures deliberately exercise containment paths
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "results.jsonl").exists()
    assert (tmp_path / "results.csv").exists()
    assert (tmp_path / "provider_config.json").exists()
    assert (tmp_path / "experiment_manifest.json").exists()
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 20
    assert len(list((tmp_path / "traces").glob("*.jsonl"))) == 20
    assert len(list((tmp_path / "reports").glob("*.json"))) == 20


def test_dialogue_only_uses_auto_and_never_executes_world_action(tmp_path: Path) -> None:
    provider = ScenarioToolProvider()
    summary = run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=provider,
        scenario_ids=["casual_chat_no_world_action"],
    )
    assert summary["pass_rate"] == 1.0
    assert summary["no_tool_call_count"] == 1
    assert summary["unexpected_no_tool_call_count"] == 0
    assert summary["dialogue_no_tool_call_count"] == 1
    assert summary["action_count"] == 0
    assert summary["tool_call_count"] == 0
    assert summary["executor_action_count"] == 0
    assert provider.requests[0]["tool_choice"] == "auto"
    trace = json.loads((tmp_path / "traces" / "casual_chat_no_world_action.jsonl").read_text())
    assert trace["event_type"] == "dialogue_turn"
    assert trace["state_delta"] == {}


def test_trace_records_sanitized_request_and_response_message(tmp_path: Path) -> None:
    provider = ScenarioToolProvider()
    run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=provider,
        scenario_ids=["save_load_world_knowledge_consistent"],
    )
    record = json.loads(
        (tmp_path / "traces" / "save_load_world_knowledge_consistent.jsonl")
        .read_text()
        .splitlines()[0]
    )
    assert record["model"]["request"]["tool_choice"] == "required"
    assert len(record["model"]["request"]["messages"]) == 2
    assert record["model"]["response_message"]["tool_calls"]
    assert "api_key" not in json.dumps(record["model"], ensure_ascii=False).lower()


def test_protocol_error_terminates_episode_without_retries(tmp_path: Path) -> None:
    turn = ToolCallingTurn(
        content=None,
        tool_calls=(
            NativeToolCall("call-1", "wait", {"seconds": 1}),
            NativeToolCall("call-2", "observe", {"target_id": "door.front"}),
        ),
        finish_reason="tool_calls",
        model="bad-model",
        request_id="req-bad",
        usage=ProviderUsage(10, 5, 15),
        latency_ms=4.0,
        raw_response_hash="c" * 64,
        response_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [],
        },
    )
    provider = OneTurnProvider(turn)
    summary = run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=provider,
        scenario_ids=["normal_observe_and_report"],
    )
    item = json.loads((tmp_path / "results.jsonl").read_text())
    assert summary["pass_count"] == 0
    assert summary["protocol_valid_count"] == 0
    assert summary["multiple_tool_call_count"] == 1
    assert summary["tool_call_count"] == 2
    assert summary["action_count"] == 0
    assert summary["executor_action_count"] == 0
    assert item["steps"] == 1
    assert item["terminal_reason"] == "model_multiple_tool_calls"
    assert len(provider.requests) == 1


def test_provider_error_is_fail_fast_and_preserved(tmp_path: Path) -> None:
    summary = run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=FailingProvider(),
        scenario_ids=["normal_observe_and_report"],
    )
    item = json.loads((tmp_path / "results.jsonl").read_text())
    assert summary["provider_error_count"] == 1
    assert summary["provider_errors"] == {"provider_timeout": 1}
    assert item["steps"] == 1
    assert item["terminal_reason"] == "provider_timeout"
    trace = json.loads((tmp_path / "traces" / "normal_observe_and_report.jsonl").read_text())
    assert trace["model"]["error"]["code"] == "provider_timeout"


def test_hidden_canonical_target_is_flagged_even_if_gateway_can_resolve_it(
    tmp_path: Path,
) -> None:
    action = load_scenario(SCENARIOS / "09_forgotten_name_filtered.json").actions[0]
    parameters = dict(action.parameters)
    parameters["target_id"] = "player"
    # Deliberately leak the hidden canonical subject instead of visitor.front_001.
    turn = ToolCallingTurn(
        content=None,
        tool_calls=(NativeToolCall("call-hidden", "report", parameters),),
        finish_reason="tool_calls",
        model="hidden-id-model",
        request_id="req-hidden",
        usage=ProviderUsage(10, 5, 15),
        latency_ms=4.0,
        raw_response_hash="d" * 64,
        response_message={"role": "assistant", "content": None, "tool_calls": []},
    )
    summary = run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=OneTurnProvider(turn),
        scenario_ids=["forgotten_name_filtered"],
    )
    item = json.loads((tmp_path / "results.jsonl").read_text())
    assert summary["hallucinated_target_count"] == 1
    assert item["grounded"] is False
    assert item["passed"] is True  # world containment and task outcome still succeeded
    assert item["clean_pass"] is False


def test_post_terminal_check_does_not_make_an_extra_model_call(tmp_path: Path) -> None:
    provider = ScenarioToolProvider()
    summary = run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=provider,
        scenario_ids=["terminal_task_rejects_more_ticks"],
    )
    item = json.loads((tmp_path / "results.jsonl").read_text())
    assert summary["pass_count"] == 1
    assert item["post_terminal_check_code"] == "TASK_TERMINAL"
    assert item["post_terminal_world_unchanged"] is True
    assert item["model_call_count"] == len(provider.requests)
    records = [
        json.loads(line)
        for line in (tmp_path / "traces" / "terminal_task_rejects_more_ticks.jsonl")
        .read_text()
        .splitlines()
    ]
    assert records[-1]["event_type"] == "post_terminal_check"


def test_non_empty_output_directory_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("do not overwrite")
    with pytest.raises(ValueError, match="not empty"):
        run_cloud_episode_experiment(
            scenario_dir=SCENARIOS,
            output_dir=tmp_path,
            provider=ScenarioToolProvider(),
            scenario_ids=["casual_chat_no_world_action"],
        )


def test_active_no_tool_call_is_counted_as_unexpected_protocol_failure(
    tmp_path: Path,
) -> None:
    turn = make_turn("normal_observe_and_report", 0, None)
    summary = run_cloud_episode_experiment(
        scenario_dir=SCENARIOS,
        output_dir=tmp_path,
        provider=OneTurnProvider(turn),
        scenario_ids=["normal_observe_and_report"],
    )
    item = json.loads((tmp_path / "results.jsonl").read_text())
    assert summary["pass_count"] == 0
    assert summary["no_tool_call_count"] == 1
    assert summary["unexpected_no_tool_call_count"] == 1
    assert summary["dialogue_no_tool_call_count"] == 0
    assert summary["tool_call_count"] == 0
    assert summary["action_count"] == 0
    assert item["terminal_reason"] == "model_no_tool_call"
    assert item["trace_complete"] is True


def test_unknown_scenario_is_rejected_before_output_directory_is_created(
    tmp_path: Path,
) -> None:
    output = tmp_path / "formal-output"
    with pytest.raises(ValueError, match="Unknown scenario IDs"):
        run_cloud_episode_experiment(
            scenario_dir=SCENARIOS,
            output_dir=output,
            provider=ScenarioToolProvider(),
            scenario_ids=["not-a-real-scenario"],
            provider_config={"model": "scripted"},
        )
    assert not output.exists()


def test_cloud_episode_cli_defaults_to_zero_provider_retries() -> None:
    args = build_parser().parse_args(["run-cloud-episodes"])
    assert args.max_retries == 0
    assert args.retry_backoff == 0.0
    assert args.tool_choice == "required"
    assert args.top_p == 1.0
    assert args.send_parallel_tool_calls is True
