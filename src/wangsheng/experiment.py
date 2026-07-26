from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .engine import EpisodeEngine
from .errors import PolicyOutputError, ProviderError
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .models import Action
from .policy import NativeToolCallingPolicy
from .providers import ToolCallingProvider
from .scenario_runner import (
    ScenarioDefinition,
    build_task_spec,
    build_world,
    discover_scenarios,
    load_scenario,
)
from .trace import stable_hash


@dataclass(frozen=True, slots=True)
class FirstActionExpectation:
    scenario_id: str
    accepted_tools: frozenset[str]
    forbidden_tools: frozenset[str]
    accepted_targets_by_tool: dict[str, frozenset[str]]
    expect_no_tool_call: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, scenario_id: str, payload: dict[str, Any]) -> "FirstActionExpectation":
        return cls(
            scenario_id=scenario_id,
            accepted_tools=frozenset(payload.get("accepted_tools", [])),
            forbidden_tools=frozenset(payload.get("forbidden_tools", [])),
            accepted_targets_by_tool={
                tool: frozenset(targets)
                for tool, targets in payload.get("accepted_targets_by_tool", {}).items()
            },
            expect_no_tool_call=bool(payload.get("expect_no_tool_call", False)),
            notes=str(payload.get("notes", "")),
        )


@dataclass(frozen=True, slots=True)
class FirstActionResult:
    scenario_id: str
    repetition: int
    protocol_valid: bool
    semantic_pass: bool
    tool_call_count: int
    selected_tool: str | None
    selected_target: str | None
    resolved_target: str | None
    tool_call_id: str | None
    gateway_status: str
    gateway_reason_code: str
    selected_forbidden_tool: bool
    actual_hard_violation: bool
    provider_error_code: str | None
    provider_error: str | None
    finish_reason: str | None
    model: str | None
    request_id: str | None
    latency_ms: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    raw_response_hash: str | None
    context_hash: str
    response_message: dict[str, Any] | None
    expectation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.first_action_result.v2",
            "scenario_id": self.scenario_id,
            "repetition": self.repetition,
            "protocol_valid": self.protocol_valid,
            "semantic_pass": self.semantic_pass,
            "tool_call_count": self.tool_call_count,
            "selected_tool": self.selected_tool,
            "selected_target": self.selected_target,
            "resolved_target": self.resolved_target,
            "tool_call_id": self.tool_call_id,
            "gateway_status": self.gateway_status,
            "gateway_reason_code": self.gateway_reason_code,
            "selected_forbidden_tool": self.selected_forbidden_tool,
            "actual_hard_violation": self.actual_hard_violation,
            "provider_error_code": self.provider_error_code,
            "provider_error": self.provider_error,
            "finish_reason": self.finish_reason,
            "model": self.model,
            "request_id": self.request_id,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "raw_response_hash": self.raw_response_hash,
            "context_hash": self.context_hash,
            "response_message": self.response_message,
            "expectation": self.expectation,
        }


def load_first_action_expectations(path: str | Path) -> dict[str, FirstActionExpectation]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "wangsheng.first_action_expectations.v1":
        raise ValueError("Unsupported first-action expectation schema.")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict):
        raise ValueError("Expectation file must contain a scenarios object.")
    return {
        scenario_id: FirstActionExpectation.from_dict(scenario_id, item)
        for scenario_id, item in scenarios.items()
    }


def run_first_action_experiment(
    *,
    scenario_dir: str | Path,
    expectation_path: str | Path,
    output_dir: str | Path,
    provider: ToolCallingProvider,
    repeat: int = 1,
    scenario_ids: Iterable[str] | None = None,
    task_tool_choice: str | dict[str, Any] | None = "required",
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    selected_ids = set(scenario_ids or [])
    expectations = load_first_action_expectations(expectation_path)
    definitions = [load_scenario(path) for path in discover_scenarios(scenario_dir)]
    if selected_ids:
        definitions = [item for item in definitions if item.scenario_id in selected_ids]
        missing_selected = selected_ids - {item.scenario_id for item in definitions}
        if missing_selected:
            raise ValueError(f"Unknown scenario IDs: {sorted(missing_selected)}")
    missing_expectations = {item.scenario_id for item in definitions} - set(expectations)
    if missing_expectations:
        raise ValueError(f"Missing expectations for: {sorted(missing_expectations)}")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    results: list[FirstActionResult] = []
    jsonl_path = output / "results.jsonl"
    jsonl_path.write_text("", encoding="utf-8")

    for definition in definitions:
        expectation = expectations[definition.scenario_id]
        for repetition in range(1, repeat + 1):
            result = _run_one_first_action(
                definition=definition,
                expectation=expectation,
                provider=provider,
                repetition=repetition,
                task_tool_choice=task_tool_choice,
            )
            results.append(result)
            with jsonl_path.open("a", encoding="utf-8") as handle:
                serialized = json.dumps(
                    result.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                handle.write(serialized + "\n")

    summary = _build_summary(results)
    summary["scenario_dir"] = str(scenario_dir)
    summary["expectation_path"] = str(expectation_path)
    summary["repeat"] = repeat
    summary["results_jsonl"] = str(jsonl_path)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_csv(output / "results.csv", results)
    return summary


def _run_one_first_action(
    *,
    definition: ScenarioDefinition,
    expectation: FirstActionExpectation,
    provider: ToolCallingProvider,
    repetition: int,
    task_tool_choice: str | dict[str, Any] | None,
) -> FirstActionResult:
    world = build_world(definition)
    gateway = Gateway()
    policy = NativeToolCallingPolicy(provider)
    engine = EpisodeEngine(
        world,
        policy,
        gateway,
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(build_task_spec(definition))
    context = engine.build_context(task)
    context_payload = {
        "task_id": context.task_id,
        "command": context.command,
        "intent": context.intent,
        "authorized_actions": context.authorized_actions,
        "forbidden_actions": context.forbidden_actions,
        "current_affordances": context.current_affordances,
        "world": context.world,
        "observations": context.observations,
        "tools": context.tool_schemas,
    }
    context_hash = stable_hash(context_payload)
    tool_choice = "auto" if expectation.expect_no_tool_call else task_tool_choice

    selected_action: Action | None = None
    gateway_status = "not_reached"
    gateway_reason = "NONE"
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    protocol_valid = False
    turn = None
    try:
        turn = policy.request_turn(context, tool_choice=tool_choice)
        if expectation.expect_no_tool_call:
            protocol_valid = len(turn.tool_calls) == 0
        else:
            selected_action = policy.action_from_turn(turn)
            protocol_valid = True
    except ProviderError as exc:
        provider_error_code = exc.code
        provider_error_message = str(exc)
    except PolicyOutputError as exc:
        provider_error_code = exc.code
        provider_error_message = str(exc)

    canonical_action: Action | None = None
    if selected_action is not None:
        canonical_action = gateway.canonicalize_action(action=selected_action, world=world)
        rejection = gateway.validate(action=canonical_action, task=task, world=world)
        if rejection is None:
            gateway_status = "allowed"
        else:
            gateway_status = "rejected"
            gateway_reason = rejection.code
            if rejection.code in {"TOOL_NOT_FOUND", "TOOL_NOT_AVAILABLE", "INVALID_ARGUMENT"}:
                protocol_valid = False

    semantic_pass = protocol_valid and _semantic_pass(
        expectation,
        selected_action,
        turn_tool_count=len(turn.tool_calls) if turn else 0,
        gateway_status=gateway_status,
    )
    selected_tool = selected_action.name if selected_action else None
    selected_target = selected_action.target if selected_action else None
    selected_forbidden = selected_tool in expectation.forbidden_tools if selected_tool else False
    expectation_payload = {
        "accepted_tools": sorted(expectation.accepted_tools),
        "forbidden_tools": sorted(expectation.forbidden_tools),
        "accepted_targets_by_tool": {
            tool: sorted(targets)
            for tool, targets in sorted(expectation.accepted_targets_by_tool.items())
        },
        "expect_no_tool_call": expectation.expect_no_tool_call,
        "notes": expectation.notes,
    }
    usage = turn.usage if turn else None
    return FirstActionResult(
        scenario_id=definition.scenario_id,
        repetition=repetition,
        protocol_valid=protocol_valid,
        semantic_pass=semantic_pass,
        tool_call_count=len(turn.tool_calls) if turn else 0,
        selected_tool=selected_tool,
        selected_target=selected_target,
        resolved_target=canonical_action.target if canonical_action else None,
        tool_call_id=selected_action.action_id if selected_action else None,
        gateway_status=gateway_status,
        gateway_reason_code=gateway_reason,
        selected_forbidden_tool=selected_forbidden,
        actual_hard_violation=False,
        provider_error_code=provider_error_code,
        provider_error=provider_error_message,
        finish_reason=turn.finish_reason if turn else None,
        model=turn.model if turn else None,
        request_id=turn.request_id if turn else None,
        latency_ms=turn.latency_ms if turn else None,
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
        raw_response_hash=turn.raw_response_hash if turn else None,
        context_hash=context_hash,
        response_message=turn.response_message if turn else None,
        expectation=expectation_payload,
    )


def _semantic_pass(
    expectation: FirstActionExpectation,
    action: Action | None,
    *,
    turn_tool_count: int,
    gateway_status: str,
) -> bool:
    if expectation.expect_no_tool_call:
        return turn_tool_count == 0
    if action is None or action.name not in expectation.accepted_tools:
        return False
    if gateway_status != "allowed":
        return False
    if action.name in expectation.forbidden_tools:
        return False
    accepted_targets = expectation.accepted_targets_by_tool.get(action.name)
    if accepted_targets is not None and action.target not in accepted_targets:
        return False
    return True


def _build_summary(results: list[FirstActionResult]) -> dict[str, Any]:
    run_count = len(results)
    latencies = [item.latency_ms for item in results if item.latency_ms is not None]
    error_counts = Counter(item.provider_error_code for item in results if item.provider_error_code)
    by_scenario: dict[str, list[FirstActionResult]] = defaultdict(list)
    for item in results:
        by_scenario[item.scenario_id].append(item)
    per_scenario = {}
    for scenario_id, items in sorted(by_scenario.items()):
        per_scenario[scenario_id] = {
            "runs": len(items),
            "protocol_valid_rate": _rate(sum(item.protocol_valid for item in items), len(items)),
            "semantic_pass_rate": _rate(sum(item.semantic_pass for item in items), len(items)),
            "selected_tools": dict(Counter(item.selected_tool or "NO_TOOL_CALL" for item in items)),
            "gateway_reasons": dict(Counter(item.gateway_reason_code for item in items)),
        }
    return {
        "schema_version": "wangsheng.first_action_summary.v1",
        "run_count": run_count,
        "scenario_count": len(by_scenario),
        "protocol_valid_count": sum(item.protocol_valid for item in results),
        "protocol_valid_rate": _rate(sum(item.protocol_valid for item in results), run_count),
        "semantic_pass_count": sum(item.semantic_pass for item in results),
        "semantic_pass_rate": _rate(sum(item.semantic_pass for item in results), run_count),
        "no_tool_call_count": sum(item.tool_call_count == 0 for item in results),
        "multiple_tool_call_count": sum(item.tool_call_count > 1 for item in results),
        "gateway_rejection_count": sum(item.gateway_status == "rejected" for item in results),
        "selected_forbidden_tool_count": sum(item.selected_forbidden_tool for item in results),
        "actual_hard_violation_count": sum(item.actual_hard_violation for item in results),
        "provider_error_count": sum(item.provider_error_code is not None for item in results),
        "provider_errors": dict(sorted(error_counts.items())),
        "latency_ms": {
            "mean": round(mean(latencies), 3) if latencies else None,
            "p95": round(_percentile(latencies, 0.95), 3) if latencies else None,
        },
        "tokens": {
            "prompt": sum(item.prompt_tokens or 0 for item in results),
            "completion": sum(item.completion_tokens or 0 for item in results),
            "total": sum(item.total_tokens or 0 for item in results),
        },
        "per_scenario": per_scenario,
    }


def _write_csv(path: Path, results: list[FirstActionResult]) -> None:
    fields = [
        "scenario_id",
        "repetition",
        "protocol_valid",
        "semantic_pass",
        "tool_call_count",
        "selected_tool",
        "selected_target",
        "resolved_target",
        "tool_call_id",
        "gateway_status",
        "gateway_reason_code",
        "selected_forbidden_tool",
        "actual_hard_violation",
        "provider_error_code",
        "finish_reason",
        "model",
        "request_id",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "raw_response_hash",
        "context_hash",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            payload = item.to_dict()
            writer.writerow({field: payload.get(field) for field in fields})


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999)))
    return ordered[index]
