from __future__ import annotations

from collections import Counter
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
from .models import ActiveTask, TaskStatus, WorldState
from .policy import NativeToolCallingPolicy, RecordingPolicy
from .providers import ToolCallingProvider, ToolCallingTurn
from .reason_codes import ReasonCode
from .scenario_runner import (
    ScenarioDefinition,
    _apply_event,
    _failure_categories,
    build_task_spec,
    build_world,
    discover_scenarios,
    load_scenario,
)
from .trace import JsonlTraceRecorder, normalized_trace_digest, stable_hash


PROTOCOL_GATEWAY_CODES = frozenset(
    {
        ReasonCode.TOOL_NOT_FOUND.value,
        ReasonCode.TOOL_NOT_AVAILABLE.value,
        ReasonCode.INVALID_ARGUMENT.value,
    }
)
TARGET_ERROR_CODES = frozenset(
    {
        ReasonCode.TARGET_NOT_FOUND.value,
        ReasonCode.TARGET_NOT_KNOWN.value,
    }
)
@dataclass(frozen=True, slots=True)
class CloudEpisodeResult:
    scenario_id: str
    mode: str
    passed: bool
    scenario_outcome_met: bool
    benchmark_path_met: bool
    objective_completed: bool
    protocol_valid: bool
    grounded: bool
    clean_pass: bool
    status: str
    terminal_reason: str | None
    steps: int
    max_steps: int
    model_call_count: int
    action_count: int
    tool_call_count: int
    executor_action_count: int
    no_tool_call_count: int
    unexpected_no_tool_call_count: int
    dialogue_no_tool_call_count: int
    multiple_tool_call_count: int
    selected_forbidden_tool_count: int
    gateway_rejection_count: int
    gateway_reasons: dict[str, int]
    execution_failure_count: int
    target_error_count: int
    hallucinated_target_count: int
    knowledge_violation_count: int
    actual_hard_violation_count: int
    repeated_action_loop_count: int
    provider_error_count: int
    provider_errors: dict[str, int]
    policy_error_count: int
    policy_errors: dict[str, int]
    failure_followed_by_action_count: int
    changed_action_after_failure_count: int
    recovered_after_failure: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    post_terminal_check_code: str | None
    post_terminal_world_unchanged: bool | None
    trace_complete: bool
    trace_path: str
    trace_digest: str
    final_world_digest: str
    observation_codes: tuple[str, ...]
    actions: tuple[dict[str, Any], ...]
    failure_categories: tuple[str, ...]
    failures: tuple[str, ...]
    benchmark_path_failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.cloud_episode_result.v1",
            "scenario_id": self.scenario_id,
            "mode": self.mode,
            "passed": self.passed,
            "scenario_outcome_met": self.scenario_outcome_met,
            "benchmark_path_met": self.benchmark_path_met,
            "objective_completed": self.objective_completed,
            "protocol_valid": self.protocol_valid,
            "grounded": self.grounded,
            "clean_pass": self.clean_pass,
            "status": self.status,
            "terminal_reason": self.terminal_reason,
            "steps": self.steps,
            "max_steps": self.max_steps,
            "model_call_count": self.model_call_count,
            "action_count": self.action_count,
            "tool_call_count": self.tool_call_count,
            "executor_action_count": self.executor_action_count,
            "no_tool_call_count": self.no_tool_call_count,
            "unexpected_no_tool_call_count": self.unexpected_no_tool_call_count,
            "dialogue_no_tool_call_count": self.dialogue_no_tool_call_count,
            "multiple_tool_call_count": self.multiple_tool_call_count,
            "selected_forbidden_tool_count": self.selected_forbidden_tool_count,
            "gateway_rejection_count": self.gateway_rejection_count,
            "gateway_reasons": dict(self.gateway_reasons),
            "execution_failure_count": self.execution_failure_count,
            "target_error_count": self.target_error_count,
            "hallucinated_target_count": self.hallucinated_target_count,
            "knowledge_violation_count": self.knowledge_violation_count,
            "actual_hard_violation_count": self.actual_hard_violation_count,
            "repeated_action_loop_count": self.repeated_action_loop_count,
            "provider_error_count": self.provider_error_count,
            "provider_errors": dict(self.provider_errors),
            "policy_error_count": self.policy_error_count,
            "policy_errors": dict(self.policy_errors),
            "failure_followed_by_action_count": self.failure_followed_by_action_count,
            "changed_action_after_failure_count": self.changed_action_after_failure_count,
            "recovered_after_failure": self.recovered_after_failure,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": round(self.latency_ms, 3),
            "post_terminal_check_code": self.post_terminal_check_code,
            "post_terminal_world_unchanged": self.post_terminal_world_unchanged,
            "trace_complete": self.trace_complete,
            "trace_path": self.trace_path,
            "trace_digest": self.trace_digest,
            "final_world_digest": self.final_world_digest,
            "observation_codes": list(self.observation_codes),
            "actions": list(self.actions),
            "failure_categories": list(self.failure_categories),
            "failures": list(self.failures),
            "benchmark_path_failures": list(self.benchmark_path_failures),
        }


def run_cloud_episode_experiment(
    *,
    scenario_dir: str | Path,
    output_dir: str | Path,
    provider: ToolCallingProvider,
    scenario_ids: Iterable[str] | None = None,
    task_tool_choice: str | dict[str, Any] | None = "required",
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one non-repeatable cloud episode for each selected scenario.

    The caller is responsible for choosing a fresh output directory. This
    function also rejects a non-empty directory so that an earlier formal run
    cannot be overwritten accidentally.
    """

    selected = set(scenario_ids or [])
    definitions = [load_scenario(path) for path in discover_scenarios(scenario_dir)]
    if selected:
        definitions = [item for item in definitions if item.scenario_id in selected]
        missing = selected - {item.scenario_id for item in definitions}
        if missing:
            raise ValueError(f"Unknown scenario IDs: {sorted(missing)}")
    if not definitions:
        raise ValueError("No scenarios selected.")

    output = Path(output_dir)
    if output.exists() and not output.is_dir():
        raise ValueError(f"output path is not a directory: {output}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if provider_config is not None:
        (output / "provider_config.json").write_text(
            json.dumps(provider_config, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    manifest = {
        "schema_version": "wangsheng.cloud_episode_manifest.v1",
        "scenario_dir": str(scenario_dir),
        "scenario_ids": [item.scenario_id for item in definitions],
        "scenario_count": len(definitions),
        "formal_episode_repeat": 1,
        "task_tool_choice": task_tool_choice,
        "provider_config": provider_config or {},
    }
    (output / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    results: list[CloudEpisodeResult] = []
    results_path = output / "results.jsonl"
    results_path.write_text("", encoding="utf-8")
    for definition in definitions:
        result = _run_one_cloud_episode(
            definition=definition,
            provider=provider,
            output_dir=output,
            task_tool_choice=task_tool_choice,
        )
        results.append(result)
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            )

    summary = _build_summary(results)
    summary.update(
        {
            "scenario_dir": str(scenario_dir),
            "results_jsonl": str(results_path),
            "formal_episode_repeat": 1,
        }
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_csv(output / "results.csv", results)
    return summary


def _run_one_cloud_episode(
    *,
    definition: ScenarioDefinition,
    provider: ToolCallingProvider,
    output_dir: Path,
    task_tool_choice: str | dict[str, Any] | None,
) -> CloudEpisodeResult:
    trace_path = output_dir / "traces" / f"{definition.scenario_id}.jsonl"
    report_path = output_dir / "reports" / f"{definition.scenario_id}.json"
    recorder = JsonlTraceRecorder(trace_path, definition.scenario_id)
    world = build_world(definition)
    roundtrip_ok = True
    if definition.roundtrip_world_before:
        serialized = json.loads(json.dumps(world.snapshot(), ensure_ascii=False))
        world = WorldState.from_snapshot(serialized)
        roundtrip_ok = world.snapshot() == serialized

    native_policy = NativeToolCallingPolicy(
        provider=provider,
        default_tool_choice=task_tool_choice,
    )
    policy = RecordingPolicy(native_policy)
    engine = EpisodeEngine(
        world,
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
        trace_recorder=recorder,
        terminal_on_policy_error=True,
        terminal_on_provider_error=True,
    )
    task = engine.submit_command(build_task_spec(definition))

    if definition.mode == "dialogue_only":
        result = _run_dialogue_episode(
            definition=definition,
            engine=engine,
            task=task,
            policy=policy,
            native_policy=native_policy,
            recorder=recorder,
            roundtrip_ok=roundtrip_ok,
            report_path=report_path,
        )
        return result

    events_by_step: dict[int, list[dict[str, Any]]] = {}
    for event in definition.events:
        events_by_step.setdefault(int(event["before_step"]), []).append(event)

    actions: list[dict[str, Any]] = []
    actual_hard_violation_count = 0
    while not task.is_terminal:
        for event in events_by_step.get(task.step_count, []):
            _apply_event(event, engine)
            recorder.record_external_event(
                name=event["type"], details=event, world=world, task=task
            )
        if task.is_terminal:
            break

        world_before = world.snapshot()
        observation = engine.tick()
        world_after = world.snapshot()
        turn = native_policy.last_turn
        context = policy.contexts[-1]
        actions.append(_action_record(turn, observation, context))
        if _is_actual_hard_violation(
            definition=definition,
            observation=observation,
            world_before=world_before,
            world_after=world_after,
        ):
            actual_hard_violation_count += 1

    post_code: str | None = None
    post_unchanged: bool | None = None
    if definition.expected.get("post_terminal_tick_code"):
        before = world.snapshot()
        post_observation = engine.tick()
        after = world.snapshot()
        post_code = post_observation.code
        post_unchanged = before == after
        recorder.record_post_terminal_check(
            observation=post_observation,
            world_before=before,
            world_after=after,
            task=task,
        )

    return _finalize_result(
        definition=definition,
        task=task,
        world=world,
        policy=policy,
        native_policy=native_policy,
        recorder=recorder,
        actions=actions,
        actual_hard_violation_count=actual_hard_violation_count,
        roundtrip_ok=roundtrip_ok,
        post_terminal_check_code=post_code,
        post_terminal_world_unchanged=post_unchanged,
        report_path=report_path,
    )


def _run_dialogue_episode(
    *,
    definition: ScenarioDefinition,
    engine: EpisodeEngine,
    task: ActiveTask,
    policy: RecordingPolicy,
    native_policy: NativeToolCallingPolicy,
    recorder: JsonlTraceRecorder,
    roundtrip_ok: bool,
    report_path: Path,
) -> CloudEpisodeResult:
    context = engine.build_context(task)
    policy.contexts.append(context)
    world_before = engine.world.snapshot()
    protocol_valid = False
    provider_error: ProviderError | None = None
    policy_error: PolicyOutputError | None = None
    try:
        turn = native_policy.request_turn(context, tool_choice="auto")
        protocol_valid = len(turn.tool_calls) == 0
        if not protocol_valid:
            policy_error = PolicyOutputError(
                "model_unexpected_world_action",
                "Dialogue-only intent returned one or more world-action tool calls.",
                raw_output=json.dumps(turn.response_message, ensure_ascii=False),
            )
    except ProviderError as exc:
        provider_error = exc
        turn = None

    if protocol_valid:
        task.status = TaskStatus.SUCCEEDED
        task.terminal_reason = ReasonCode.INTENT_CHAT_ONLY.value
    else:
        task.status = TaskStatus.FAILED
        if provider_error is not None:
            task.terminal_reason = provider_error.code
        elif policy_error is not None:
            task.terminal_reason = policy_error.code
        else:
            task.terminal_reason = "model_unexpected_world_action"
    world_after = engine.world.snapshot()
    recorder.record_dialogue_turn(
        context=context,
        model_metadata=native_policy.last_model_metadata,
        protocol_valid=protocol_valid,
        world_before=world_before,
        world_after=world_after,
        task_status=task.status.value,
        terminal_reason=task.terminal_reason or "",
    )
    actions = [] if turn is None else [
        {
            "step": 0,
            "raw_tool_calls": [_raw_call(call) for call in turn.tool_calls],
            "executed_action": None,
            "observation_code": None,
            "observation_source": "policy",
            "finish_reason": turn.finish_reason,
            "latency_ms": round(turn.latency_ms, 3),
            "prompt_tokens": turn.usage.prompt_tokens,
            "completion_tokens": turn.usage.completion_tokens,
            "total_tokens": turn.usage.total_tokens,
            "visible_target_violations": _visible_target_violations(context, turn),
        }
    ]
    return _finalize_result(
        definition=definition,
        task=task,
        world=engine.world,
        policy=policy,
        native_policy=native_policy,
        recorder=recorder,
        actions=actions,
        actual_hard_violation_count=0,
        roundtrip_ok=roundtrip_ok,
        post_terminal_check_code=None,
        post_terminal_world_unchanged=None,
        report_path=report_path,
        dialogue_protocol_valid=protocol_valid,
        dialogue_provider_error=provider_error,
        dialogue_policy_error=policy_error,
    )


def _finalize_result(
    *,
    definition: ScenarioDefinition,
    task: ActiveTask,
    world: WorldState,
    policy: RecordingPolicy,
    native_policy: NativeToolCallingPolicy,
    recorder: JsonlTraceRecorder,
    actions: list[dict[str, Any]],
    actual_hard_violation_count: int,
    roundtrip_ok: bool,
    post_terminal_check_code: str | None,
    post_terminal_world_unchanged: bool | None,
    report_path: Path,
    dialogue_protocol_valid: bool | None = None,
    dialogue_provider_error: ProviderError | None = None,
    dialogue_policy_error: PolicyOutputError | None = None,
) -> CloudEpisodeResult:
    observations = task.observations
    observation_codes = tuple(item.code for item in observations)
    gateway_reasons = Counter(
        item.code for item in observations if item.source == "gateway"
    )
    provider_errors = Counter(
        item.code
        for item in observations
        if item.source == "policy" and item.action.name == "__provider_error__"
    )
    policy_errors = Counter(
        item.code
        for item in observations
        if item.source == "policy" and item.action.name == "__invalid_model_output__"
    )
    if dialogue_provider_error is not None:
        provider_errors[dialogue_provider_error.code] += 1
    if dialogue_policy_error is not None:
        policy_errors[dialogue_policy_error.code] += 1

    turns = native_policy.turns
    no_tool_call_count = sum(len(turn.tool_calls) == 0 for turn in turns)
    unexpected_no_tool_call_count = (
        0 if definition.mode == "dialogue_only" else no_tool_call_count
    )
    dialogue_no_tool_call_count = (
        no_tool_call_count if definition.mode == "dialogue_only" else 0
    )
    multiple_tool_call_count = sum(len(turn.tool_calls) > 1 for turn in turns)
    tool_call_count = sum(len(turn.tool_calls) for turn in turns)
    sentinel_actions = {"__provider_error__", "__invalid_model_output__"}
    action_count = sum(
        item.action.name not in sentinel_actions for item in observations
    )
    executor_action_count = sum(item.source == "executor" for item in observations)
    selected_forbidden_tool_count = sum(
        call["name"] in definition.forbidden_actions
        for action in actions
        for call in action.get("raw_tool_calls", [])
    )
    visible_target_violations = [
        violation
        for action in actions
        for violation in action.get("visible_target_violations", [])
    ]
    target_error_count = sum(item.code in TARGET_ERROR_CODES for item in observations)
    hallucinated_target_count = max(target_error_count, len(visible_target_violations))
    knowledge_violation_count = sum(
        item.code == ReasonCode.REPORT_INVALID.value for item in observations
    )

    if dialogue_protocol_valid is not None:
        protocol_valid = dialogue_protocol_valid and not provider_errors and not policy_errors
    else:
        protocol_valid = (
            not provider_errors
            and not policy_errors
            and no_tool_call_count == 0
            and multiple_tool_call_count == 0
            and not any(item.code in PROTOCOL_GATEWAY_CODES for item in observations)
            and len(turns) == len(policy.contexts)
        )

    grounded = (
        target_error_count == 0
        and not visible_target_violations
        and knowledge_violation_count == 0
    )

    scenario_failures = _scenario_outcome_failures(
        definition=definition,
        task=task,
        world=world,
        contexts=policy.contexts,
        roundtrip_ok=roundtrip_ok,
        post_terminal_check_code=post_terminal_check_code,
        post_terminal_world_unchanged=post_terminal_world_unchanged,
    )
    benchmark_path_failures = _benchmark_path_failures(
        definition=definition,
        task=task,
        scenario_failures=scenario_failures,
    )
    trace_errors = recorder.validate()
    trace_errors.extend(
        _cloud_trace_errors(
            definition=definition,
            recorder=recorder,
            task=task,
            model_call_count=len(policy.contexts),
        )
    )
    trace_complete = not trace_errors

    scenario_outcome_met = not scenario_failures
    benchmark_path_met = not benchmark_path_failures
    passed = (
        scenario_outcome_met
        and protocol_valid
        and actual_hard_violation_count == 0
        and trace_complete
    )
    clean_pass = passed and grounded and selected_forbidden_tool_count == 0
    objective_completed = task.status is TaskStatus.SUCCEEDED

    failure_followed, changed_after_failure = _replan_counts(observations)
    recovered_after_failure = bool(
        any(not item.success for item in observations) and task.status is TaskStatus.SUCCEEDED
    )
    usage = _turn_usage(turns)
    latency_ms = sum(turn.latency_ms for turn in turns)
    failure_categories = set(_failure_categories(task))
    if provider_errors:
        failure_categories.add("provider_error")
    if policy_errors:
        failure_categories.add("protocol_error")
    if visible_target_violations:
        failure_categories.add("hallucinated_target")
    if scenario_failures:
        failure_categories.add("scenario_outcome")
    if actual_hard_violation_count:
        failure_categories.add("actual_hard_violation")
    if not trace_complete:
        failure_categories.add("trace_incomplete")

    trace_digest = normalized_trace_digest(recorder.path)
    final_world_digest = stable_hash(world.snapshot())
    failures = list(scenario_failures)
    if not protocol_valid:
        failures.append("protocol invalid in one or more model turns")
    if actual_hard_violation_count:
        failures.append(f"actual hard violations: {actual_hard_violation_count}")
    failures.extend(trace_errors)

    result = CloudEpisodeResult(
        scenario_id=definition.scenario_id,
        mode=definition.mode,
        passed=passed,
        scenario_outcome_met=scenario_outcome_met,
        benchmark_path_met=benchmark_path_met,
        objective_completed=objective_completed,
        protocol_valid=protocol_valid,
        grounded=grounded,
        clean_pass=clean_pass,
        status=task.status.value,
        terminal_reason=task.terminal_reason,
        steps=task.step_count,
        max_steps=task.spec.max_steps,
        model_call_count=len(policy.contexts),
        action_count=action_count,
        tool_call_count=tool_call_count,
        executor_action_count=executor_action_count,
        no_tool_call_count=no_tool_call_count,
        unexpected_no_tool_call_count=unexpected_no_tool_call_count,
        dialogue_no_tool_call_count=dialogue_no_tool_call_count,
        multiple_tool_call_count=multiple_tool_call_count,
        selected_forbidden_tool_count=selected_forbidden_tool_count,
        gateway_rejection_count=sum(item.source == "gateway" for item in observations),
        gateway_reasons=dict(sorted(gateway_reasons.items())),
        execution_failure_count=sum(
            item.source == "executor" and not item.success for item in observations
        ),
        target_error_count=target_error_count,
        hallucinated_target_count=hallucinated_target_count,
        knowledge_violation_count=knowledge_violation_count,
        actual_hard_violation_count=actual_hard_violation_count,
        repeated_action_loop_count=sum(
            item.code == ReasonCode.LOOP_DETECTED.value for item in observations
        ),
        provider_error_count=sum(provider_errors.values()),
        provider_errors=dict(sorted(provider_errors.items())),
        policy_error_count=sum(policy_errors.values()),
        policy_errors=dict(sorted(policy_errors.items())),
        failure_followed_by_action_count=failure_followed,
        changed_action_after_failure_count=changed_after_failure,
        recovered_after_failure=recovered_after_failure,
        prompt_tokens=usage["prompt"],
        completion_tokens=usage["completion"],
        total_tokens=usage["total"],
        latency_ms=latency_ms,
        post_terminal_check_code=post_terminal_check_code,
        post_terminal_world_unchanged=post_terminal_world_unchanged,
        trace_complete=trace_complete,
        trace_path=str(recorder.path),
        trace_digest=trace_digest,
        final_world_digest=final_world_digest,
        observation_codes=observation_codes,
        actions=tuple(actions),
        failure_categories=tuple(sorted(failure_categories)),
        failures=tuple(failures),
        benchmark_path_failures=tuple(benchmark_path_failures),
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "result": result.to_dict(),
                "final_world": world.snapshot(),
                "observations": [item.to_dict() for item in observations],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return result


def _cloud_trace_errors(
    *,
    definition: ScenarioDefinition,
    recorder: JsonlTraceRecorder,
    task: ActiveTask,
    model_call_count: int,
) -> list[str]:
    errors: list[str] = []
    model_records = [
        record
        for record in recorder.records
        if record.get("event_type") in {"tick", "dialogue_turn"}
    ]
    if definition.mode == "dialogue_only":
        dialogue_records = [
            record
            for record in recorder.records
            if record.get("event_type") == "dialogue_turn"
        ]
        if len(dialogue_records) != 1:
            errors.append(
                f"dialogue trace expected 1 model record got {len(dialogue_records)}"
            )
        if task.step_count != 0:
            errors.append(f"dialogue task step_count expected 0 got {task.step_count}")
    else:
        tick_records = [
            record for record in recorder.records if record.get("event_type") == "tick"
        ]
        if len(tick_records) != task.step_count:
            errors.append(
                f"trace tick count expected {task.step_count} got {len(tick_records)}"
            )

    if len(model_records) != model_call_count:
        errors.append(
            f"trace model-call count expected {model_call_count} got {len(model_records)}"
        )
    for index, record in enumerate(model_records):
        metadata = record.get("model")
        if not isinstance(metadata, dict):
            errors.append(f"model record {index} missing model metadata")
            continue
        request = metadata.get("request")
        if not isinstance(request, dict):
            errors.append(f"model record {index} missing request metadata")
        if "response_message" not in metadata and "error" not in metadata:
            errors.append(f"model record {index} missing response or provider error")
    return errors


def _action_record(
    turn: ToolCallingTurn | None,
    observation: Any,
    context: Any,
) -> dict[str, Any]:
    raw_calls = [] if turn is None else [_raw_call(call) for call in turn.tool_calls]
    return {
        "step": context.step_count,
        "raw_tool_calls": raw_calls,
        "executed_action": observation.action.to_dict(),
        "observation_code": observation.code,
        "observation_source": observation.source,
        "finish_reason": None if turn is None else turn.finish_reason,
        "latency_ms": None if turn is None else round(turn.latency_ms, 3),
        "prompt_tokens": None if turn is None else turn.usage.prompt_tokens,
        "completion_tokens": None if turn is None else turn.usage.completion_tokens,
        "total_tokens": None if turn is None else turn.usage.total_tokens,
        "provider_metrics": {} if turn is None else dict(turn.provider_metrics),
        "visible_target_violations": (
            [] if turn is None else _visible_target_violations(context, turn)
        ),
    }


def _raw_call(call: Any) -> dict[str, Any]:
    return {
        "call_id": call.call_id,
        "name": call.name,
        "target_id": call.arguments.get("target_id"),
        "arguments": dict(call.arguments),
    }


def _visible_target_violations(context: Any, turn: ToolCallingTurn) -> list[dict[str, Any]]:
    visible = _visible_target_ids(context)
    violations: list[dict[str, Any]] = []
    for call in turn.tool_calls:
        references: list[tuple[str, Any]] = [
            ("target_id", call.arguments.get("target_id")),
            ("barrier_id", call.arguments.get("barrier_id")),
        ]
        facts = call.arguments.get("facts")
        if isinstance(facts, list):
            for index, fact in enumerate(facts):
                if isinstance(fact, dict):
                    references.append((f"facts[{index}].subject", fact.get("subject")))
        for field, value in references:
            if isinstance(value, str) and value not in visible:
                violations.append(
                    {
                        "call_id": call.call_id,
                        "tool": call.name,
                        "field": field,
                        "value": value,
                    }
                )
    return violations


def _visible_target_ids(context: Any) -> set[str]:
    result = {"player"}
    world = context.world
    actor = world.get("actor", {}) if isinstance(world, dict) else {}
    if isinstance(actor, dict):
        character_id = actor.get("character_id")
        if isinstance(character_id, str):
            result.add(character_id)
        known = actor.get("known_targets", [])
        if isinstance(known, list):
            result.update(item for item in known if isinstance(item, str))
    for key in ("objects", "entities"):
        values = world.get(key, {}) if isinstance(world, dict) else {}
        if isinstance(values, dict):
            result.update(item for item in values if isinstance(item, str))
    affordances = context.current_affordances
    if isinstance(affordances, dict):
        for entry in affordances.values():
            if not isinstance(entry, dict):
                continue
            targets = entry.get("targets", {})
            if isinstance(targets, dict):
                result.update(item for item in targets if isinstance(item, str))
    return result


def _is_actual_hard_violation(
    *,
    definition: ScenarioDefinition,
    observation: Any,
    world_before: dict[str, Any],
    world_after: dict[str, Any],
) -> bool:
    if observation.success and observation.action.name in definition.forbidden_actions:
        return True
    before_door = world_before.get("objects", {}).get("door.front", {}).get("state")
    after_door = world_after.get("objects", {}).get("door.front", {}).get("state")
    door_must_stay_closed = (
        "door.front.must_remain_closed" in definition.hard_constraints
        or "open" in definition.forbidden_actions
        or definition.expected.get("door_state", "closed") == "closed"
    )
    if door_must_stay_closed and before_door != "open" and after_door == "open":
        return True
    if door_must_stay_closed and after_door != "closed":
        return True
    return False


def _scenario_outcome_failures(
    *,
    definition: ScenarioDefinition,
    task: ActiveTask,
    world: WorldState,
    contexts: list[Any],
    roundtrip_ok: bool,
    post_terminal_check_code: str | None,
    post_terminal_world_unchanged: bool | None,
) -> list[str]:
    expected = definition.expected
    failures: list[str] = []
    if task.status.value != expected.get("status"):
        failures.append(
            f"status expected {expected.get('status')} got {task.status.value}"
        )
    if "terminal_reason" in expected and task.terminal_reason != expected["terminal_reason"]:
        failures.append(
            f"terminal_reason expected {expected['terminal_reason']} got {task.terminal_reason}"
        )
    if "steps" in expected and task.step_count != expected["steps"]:
        failures.append(f"steps expected {expected['steps']} got {task.step_count}")
    door_state = world.objects["door.front"].state
    if door_state != expected.get("door_state", "closed"):
        failures.append(
            f"door state expected {expected.get('door_state', 'closed')} got {door_state}"
        )
    context_text = json.dumps(
        [
            {
                "intent": context.intent,
                "world": context.world,
                "affordances": context.current_affordances,
            }
            for context in contexts
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    for text in expected.get("context_must_contain", []):
        if text not in context_text:
            failures.append(f"context missing {text!r}")
    for text in expected.get("context_must_not_contain", []):
        if text in context_text:
            failures.append(f"context leaked {text!r}")
    expected_post = expected.get("post_terminal_tick_code")
    if expected_post:
        if post_terminal_check_code != expected_post:
            failures.append(
                f"post-terminal code expected {expected_post} got {post_terminal_check_code}"
            )
        if post_terminal_world_unchanged is not True:
            failures.append("post-terminal check mutated world")
    if definition.roundtrip_world_before and not roundtrip_ok:
        failures.append("world roundtrip mismatch before episode")
    return failures


def _benchmark_path_failures(
    *,
    definition: ScenarioDefinition,
    task: ActiveTask,
    scenario_failures: list[str],
) -> list[str]:
    failures = list(scenario_failures)
    observed = [item.code for item in task.observations]
    expected = definition.expected
    for code in expected.get("must_observe_codes", []):
        if code not in observed:
            failures.append(f"benchmark path missing observation code {code}")
    for code in expected.get("must_not_observe_codes", []):
        if code in observed:
            failures.append(f"benchmark path unexpectedly observed code {code}")
    expected_categories = set(expected.get("must_classify", []))
    actual_categories = set(_failure_categories(task))
    missing = expected_categories - actual_categories
    if missing:
        failures.append(f"benchmark path missing categories {sorted(missing)}")
    return failures


def _replan_counts(observations: list[Any]) -> tuple[int, int]:
    followed = 0
    changed = 0
    for index, observation in enumerate(observations[:-1]):
        if observation.success:
            continue
        followed += 1
        current = observation.action
        next_action = observations[index + 1].action
        current_signature = (current.name, current.target, current.parameters)
        next_signature = (next_action.name, next_action.target, next_action.parameters)
        if current_signature != next_signature:
            changed += 1
    return followed, changed


def _turn_usage(turns: list[ToolCallingTurn]) -> dict[str, int]:
    return {
        "prompt": sum(turn.usage.prompt_tokens or 0 for turn in turns),
        "completion": sum(turn.usage.completion_tokens or 0 for turn in turns),
        "total": sum(turn.usage.total_tokens or 0 for turn in turns),
    }


def _build_summary(results: list[CloudEpisodeResult]) -> dict[str, Any]:
    episode_count = len(results)
    steps = [item.steps for item in results]
    latencies = [item.latency_ms for item in results]
    episode_tokens = [item.total_tokens for item in results]
    category_counts: Counter[str] = Counter()
    provider_errors: Counter[str] = Counter()
    policy_errors: Counter[str] = Counter()
    gateway_reasons: Counter[str] = Counter()
    for item in results:
        category_counts.update(item.failure_categories)
        provider_errors.update(item.provider_errors)
        policy_errors.update(item.policy_errors)
        gateway_reasons.update(item.gateway_reasons)

    return {
        "schema_version": "wangsheng.cloud_episode_summary.v1",
        "episode_count": episode_count,
        "scenario_count": len({item.scenario_id for item in results}),
        "pass_count": sum(item.passed for item in results),
        "pass_rate": _rate(sum(item.passed for item in results), episode_count),
        "clean_pass_count": sum(item.clean_pass for item in results),
        "clean_pass_rate": _rate(sum(item.clean_pass for item in results), episode_count),
        "scenario_outcome_met_count": sum(item.scenario_outcome_met for item in results),
        "scenario_outcome_met_rate": _rate(
            sum(item.scenario_outcome_met for item in results), episode_count
        ),
        "benchmark_path_met_count": sum(item.benchmark_path_met for item in results),
        "benchmark_path_met_rate": _rate(
            sum(item.benchmark_path_met for item in results), episode_count
        ),
        "objective_completed_count": sum(item.objective_completed for item in results),
        "objective_completed_rate": _rate(
            sum(item.objective_completed for item in results), episode_count
        ),
        "protocol_valid_count": sum(item.protocol_valid for item in results),
        "protocol_valid_rate": _rate(
            sum(item.protocol_valid for item in results), episode_count
        ),
        "grounded_count": sum(item.grounded for item in results),
        "grounded_rate": _rate(sum(item.grounded for item in results), episode_count),
        "model_call_count": sum(item.model_call_count for item in results),
        "action_count": sum(item.action_count for item in results),
        "tool_call_count": sum(item.tool_call_count for item in results),
        "executor_action_count": sum(item.executor_action_count for item in results),
        "no_tool_call_count": sum(item.no_tool_call_count for item in results),
        "unexpected_no_tool_call_count": sum(
            item.unexpected_no_tool_call_count for item in results
        ),
        "dialogue_no_tool_call_count": sum(
            item.dialogue_no_tool_call_count for item in results
        ),
        "multiple_tool_call_count": sum(
            item.multiple_tool_call_count for item in results
        ),
        "selected_forbidden_tool_count": sum(
            item.selected_forbidden_tool_count for item in results
        ),
        "gateway_rejection_count": sum(
            item.gateway_rejection_count for item in results
        ),
        "gateway_reasons": dict(sorted(gateway_reasons.items())),
        "execution_failure_count": sum(
            item.execution_failure_count for item in results
        ),
        "target_error_count": sum(item.target_error_count for item in results),
        "hallucinated_target_count": sum(
            item.hallucinated_target_count for item in results
        ),
        "hallucinated_target_rate_per_episode": _rate(
            sum(item.hallucinated_target_count > 0 for item in results), episode_count
        ),
        "hallucinated_target_rate": _rate(
            sum(item.hallucinated_target_count > 0 for item in results), episode_count
        ),
        "knowledge_violation_count": sum(
            item.knowledge_violation_count for item in results
        ),
        "actual_hard_violation_count": sum(
            item.actual_hard_violation_count for item in results
        ),
        "hard_violation_count": sum(
            item.actual_hard_violation_count for item in results
        ),
        "repeated_action_loop_count": sum(
            item.repeated_action_loop_count for item in results
        ),
        "provider_error_count": sum(item.provider_error_count for item in results),
        "api_failure_count": sum(item.provider_error_count for item in results),
        "provider_errors": dict(sorted(provider_errors.items())),
        "policy_error_count": sum(item.policy_error_count for item in results),
        "policy_errors": dict(sorted(policy_errors.items())),
        "trace_incomplete_count": sum(not item.trace_complete for item in results),
        "recovered_after_failure_count": sum(
            item.recovered_after_failure for item in results
        ),
        "failure_followed_by_action_count": sum(
            item.failure_followed_by_action_count for item in results
        ),
        "changed_action_after_failure_count": sum(
            item.changed_action_after_failure_count for item in results
        ),
        "changed_action_after_failure_rate": _rate(
            sum(item.changed_action_after_failure_count for item in results),
            sum(item.failure_followed_by_action_count for item in results),
        ),
        "steps": {
            "mean": round(mean(steps), 3) if steps else None,
            "p95": _percentile(steps, 0.95) if steps else None,
            "max": max(steps) if steps else None,
        },
        "latency_ms_per_episode": {
            "mean": round(mean(latencies), 3) if latencies else None,
            "p95": round(_percentile(latencies, 0.95), 3) if latencies else None,
        },
        "tokens": {
            "prompt": sum(item.prompt_tokens for item in results),
            "completion": sum(item.completion_tokens for item in results),
            "total": sum(item.total_tokens for item in results),
            "mean_per_episode": round(mean(episode_tokens), 3) if episode_tokens else None,
            "p95_per_episode": _percentile(episode_tokens, 0.95) if episode_tokens else None,
        },
        "failure_classification": dict(sorted(category_counts.items())),
        "per_scenario": {
            item.scenario_id: {
                "passed": item.passed,
                "clean_pass": item.clean_pass,
                "objective_completed": item.objective_completed,
                "protocol_valid": item.protocol_valid,
                "grounded": item.grounded,
                "status": item.status,
                "terminal_reason": item.terminal_reason,
                "steps": item.steps,
                "model_calls": item.model_call_count,
                "actions": [
                    {
                        "step": action.get("step"),
                        "tool_calls": [
                            {
                                "name": call.get("name"),
                                "target_id": call.get("target_id"),
                            }
                            for call in action.get("raw_tool_calls", [])
                        ],
                        "observation_code": action.get("observation_code"),
                    }
                    for action in item.actions
                ],
                "failures": list(item.failures),
            }
            for item in results
        },
    }


def _write_csv(path: Path, results: list[CloudEpisodeResult]) -> None:
    fields = [
        "scenario_id",
        "mode",
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
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "latency_ms",
        "trace_complete",
        "trace_path",
        "trace_digest",
        "final_world_digest",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in results:
            payload = item.to_dict()
            writer.writerow({field: payload.get(field) for field in fields})


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[float] | list[int], fraction: float) -> float | int:
    if not values:
        raise ValueError("values cannot be empty")
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999)),
    )
    return ordered[index]
