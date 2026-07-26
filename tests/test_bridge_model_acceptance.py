from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from wangsheng.bridge.model_acceptance import (
    discover_model_scenarios,
    load_model_scenario,
    run_one_model_bridge_scenario,
    run_model_bridge_soak,
)
from wangsheng.providers import NativeToolCall, ProviderUsage, ToolCallingTurn


@dataclass(slots=True)
class AdaptiveScenarioProvider:
    actions: list[dict[str, Any]]
    _index: int = 0
    requests: list[dict[str, Any]] = field(default_factory=list)

    def complete_tool_call(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ToolCallingTurn:
        self.requests.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        if not tools:
            return _turn(content="The rain does sound different tonight.", call=None, index=self._index)
        if self._index >= len(self.actions):
            action = {"name": "wait", "parameters": {"seconds": 0}}
        else:
            action = self.actions[self._index]
            self._index += 1
        arguments = dict(action.get("parameters", {}))
        target = action.get("target")
        if target is not None:
            arguments["target_id"] = target
        fact_type = arguments.pop("fact_type", None)
        if fact_type:
            payload = json.loads(messages[-1]["content"])
            candidates = payload["world"]["reportable_facts"]
            match = next(item for item in candidates if item["predicate"] == fact_type)
            arguments["fact_ids"] = [match["fact_id"]]
        call = NativeToolCall(
            call_id=f"call.{self._index:04d}",
            name=str(action["name"]),
            arguments=arguments,
        )
        return _turn(content=None, call=call, index=self._index)


def _turn(*, content: str | None, call: NativeToolCall | None, index: int) -> ToolCallingTurn:
    calls = () if call is None else (call,)
    response = {
        "role": "assistant",
        "content": content,
        "tool_calls": [item.to_dict() for item in calls],
    }
    raw = json.dumps(response, sort_keys=True)
    return ToolCallingTurn(
        content=content,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        model="scripted-bridge-model",
        request_id=f"request.{index:04d}",
        usage=ProviderUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
        latency_ms=1.0,
        raw_response_hash=sha256(raw.encode()).hexdigest(),
        response_message=response,
        provider_name="scripted",
    )


def test_frozen_model_scenario_catalog() -> None:
    paths = discover_model_scenarios("scenarios_bridge_model_v060")
    assert len(paths) == 20
    scenarios = [load_model_scenario(path) for path in paths]
    assert len({item.scenario_id for item in scenarios}) == 20
    assert sum(item.category == "basic_async" for item in scenarios) == 8
    assert sum(item.category == "fault_recovery" for item in scenarios) == 8
    assert sum(item.category == "save_load_recovery" for item in scenarios) == 4


def test_all_reference_paths_pass_model_bridge_acceptance(tmp_path: Path) -> None:
    for path in discover_model_scenarios("scenarios_bridge_model_v060"):
        scenario = load_model_scenario(path)
        provider = AdaptiveScenarioProvider(list(scenario.scripted_actions))
        result = run_one_model_bridge_scenario(
            scenario=scenario,
            provider=provider,
            output_dir=tmp_path / scenario.scenario_id,
        )
        assert result.passed, (scenario.scenario_id, result.failures)
        assert result.hard_violation_count == 0
        assert result.stale_response_applied_count == 0
        assert result.post_cancel_mutation_count == 0
        assert result.duplicate_world_mutation_count == 0
        assert result.invalid_lifecycle_transition_count == 0
        assert result.save_load_digest_mismatch_count == 0
        assert result.trace_incomplete_count == 0


def test_short_soak_keeps_infrastructure_safe(tmp_path: Path) -> None:
    cycle = [
        {"name": "move_to", "target": "door.front", "parameters": {}},
        {
            "name": "ask_through",
            "target": "visitor.xiaoman",
            "parameters": {"barrier_id": "door.front", "topic": "identity"},
        },
        {"name": "move_to", "target": "player", "parameters": {}},
        {"name": "report", "target": "player", "parameters": {"fact_type": "claimed_name"}},
    ] * 20
    provider = AdaptiveScenarioProvider(cycle)
    summary = run_model_bridge_soak(
        provider=provider,
        output_dir=tmp_path / "soak",
        duration_seconds=1,
        decision_interval_seconds=0.01,
        fault_schedule={"cancel": 1, "world_event": 1, "pause_resume": 1, "save_load": 1, "provider_timeout": 1},
    )
    assert summary["all_infrastructure_gates_passed"] is True
