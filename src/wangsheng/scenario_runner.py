from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean
from typing import Any

from .contracts import Intent, IntentKind, MemoryEvent
from .engine import EpisodeEngine
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .models import Action, ActiveTask, TaskSpec, TaskStatus, WorldState
from .policy import ModelPolicy, RecordingPolicy
from .providers import ScriptedTextProvider
from .reason_codes import ReasonCode
from .scenarios import ALL_TOOLS, door_visitor_world
from .trace import JsonlTraceRecorder, stable_hash, write_episode_summary


FAILURE_CATEGORY_BY_CODE = {
    ReasonCode.TOOL_NOT_FOUND.value: "protocol_error",
    ReasonCode.TOOL_NOT_AVAILABLE.value: "protocol_error",
    ReasonCode.INVALID_ARGUMENT.value: "invalid_argument",
    ReasonCode.TARGET_NOT_FOUND.value: "target_error",
    ReasonCode.TARGET_NOT_KNOWN.value: "target_error",
    ReasonCode.NO_PERMISSION.value: "permission_error",
    ReasonCode.HARD_CONSTRAINT_VIOLATION.value: "hard_constraint",
    ReasonCode.REPORT_INVALID.value: "knowledge_violation",
    ReasonCode.LOOP_DETECTED.value: "loop",
    ReasonCode.TASK_CANCELLED.value: "cancelled",
    ReasonCode.NO_PATH.value: "execution_failure",
    ReasonCode.TOO_FAR.value: "execution_failure",
    ReasonCode.LOCKED.value: "execution_failure",
    ReasonCode.NO_RESPONSE.value: "execution_failure",
    ReasonCode.TIMEOUT.value: "execution_failure",
    ReasonCode.INTERRUPTED.value: "execution_failure",
}
FAILURE_CATEGORIES = (
    "protocol_error",
    "invalid_argument",
    "target_error",
    "permission_error",
    "hard_constraint",
    "execution_failure",
    "knowledge_violation",
    "loop",
    "cancelled",
    "max_steps",
    "other",
)


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    command: str
    required_report_fact: str | None
    max_steps: int
    allowed_actions: frozenset[str]
    forbidden_actions: frozenset[str]
    hard_constraints: frozenset[str]
    completion: dict[str, Any]
    intent: Intent
    mode: str
    world: dict[str, Any]
    actions: tuple[Action, ...]
    events: tuple[dict[str, Any], ...]
    roundtrip_world_before: bool
    expected: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    passed: bool
    status: str
    terminal_reason: str | None
    steps: int
    rejection_count: int
    execution_failure_count: int
    hard_violation_count: int
    trace_complete: bool
    trace_path: str
    trace_digest: str
    failure_categories: tuple[str, ...]
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "status": self.status,
            "terminal_reason": self.terminal_reason,
            "steps": self.steps,
            "rejection_count": self.rejection_count,
            "execution_failure_count": self.execution_failure_count,
            "hard_violation_count": self.hard_violation_count,
            "trace_complete": self.trace_complete,
            "trace_path": self.trace_path,
            "trace_digest": self.trace_digest,
            "failure_categories": list(self.failure_categories),
            "failures": list(self.failures),
        }


def load_scenario(path: str | Path) -> ScenarioDefinition:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    task = payload.get("task", {})
    intent_payload = payload.get("intent", {"kind": "task", "text": task.get("command", "")})
    intent = Intent(
        intent_id=intent_payload.get("intent_id", f"intent.{payload['scenario_id']}"),
        kind=IntentKind(intent_payload.get("kind", "task")),
        text=intent_payload.get("text", task.get("command", "")),
        source=intent_payload.get("source", "player"),
    )
    return ScenarioDefinition(
        scenario_id=payload["scenario_id"],
        command=task.get("command", intent.text),
        required_report_fact=task.get("required_report_fact"),
        max_steps=task.get("max_steps", 12),
        allowed_actions=frozenset(task.get("allowed_actions", sorted(ALL_TOOLS))),
        forbidden_actions=frozenset(task.get("forbidden_actions", [])),
        hard_constraints=frozenset(task.get("hard_constraints", [])),
        completion=dict(task.get("completion", {})),
        intent=intent,
        mode=payload.get("mode", "agent"),
        world=payload.get("world", {}),
        actions=tuple(Action(item["name"], item.get("target"), item.get("parameters", {})) for item in payload.get("scripted_actions", [])),
        events=tuple(payload.get("events", [])),
        roundtrip_world_before=bool(payload.get("roundtrip_world_before", False)),
        expected=payload["expected"],
    )


def discover_scenarios(directory: str | Path) -> list[Path]:
    return sorted(Path(directory).glob("*.json"))



def build_world(definition: ScenarioDefinition) -> WorldState:
    world = door_visitor_world()
    _apply_world_overrides(world, definition.world)
    return world


def build_task_spec(definition: ScenarioDefinition) -> TaskSpec:
    return TaskSpec(
        definition.scenario_id,
        definition.command,
        definition.allowed_actions,
        definition.forbidden_actions,
        definition.required_report_fact,
        definition.hard_constraints,
        definition.max_steps,
        definition.completion,
        definition.intent,
    )

def run_scenario(definition: ScenarioDefinition, output_dir: str | Path) -> ScenarioResult:
    output = Path(output_dir)
    trace_path = output / "traces" / f"{definition.scenario_id}.jsonl"
    report_path = output / "reports" / f"{definition.scenario_id}.json"
    world = build_world(definition)
    if definition.roundtrip_world_before:
        snapshot = json.loads(json.dumps(world.snapshot(), ensure_ascii=False))
        world = WorldState.from_snapshot(snapshot)
    recorder = JsonlTraceRecorder(trace_path, definition.scenario_id)

    if definition.mode == "dialogue_only":
        synthetic_task = ActiveTask(
            TaskSpec(
                definition.scenario_id,
                definition.command,
                frozenset(),
                frozenset(),
                None,
                max_steps=0,
                intent=definition.intent,
            ),
            status=TaskStatus.SUCCEEDED,
            terminal_reason=ReasonCode.INTENT_CHAT_ONLY.value,
        )
        recorder.record_intent(intent=definition.intent, world=world, task_status=synthetic_task.status.value)
        write_episode_summary(report_path, task=synthetic_task, world=world, trace_path=trace_path)
        failures = _evaluate_dialogue_expected(definition, world, recorder)
        return ScenarioResult(
            scenario_id=definition.scenario_id,
            passed=not failures,
            status=synthetic_task.status.value,
            terminal_reason=synthetic_task.terminal_reason,
            steps=0,
            rejection_count=0,
            execution_failure_count=0,
            hard_violation_count=0,
            trace_complete=not recorder.validate(),
            trace_path=str(trace_path),
            trace_digest=stable_hash([_stable_record(record) for record in recorder.records]),
            failure_categories=(),
            failures=tuple(failures),
        )

    task_spec = build_task_spec(definition)
    responses = [
        json.dumps(
            {"name": action.name, "target": action.target, "parameters": action.parameters},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for action in definition.actions
    ]
    policy = RecordingPolicy(ModelPolicy(ScriptedTextProvider(responses)))
    engine = EpisodeEngine(world, policy, Gateway(), SimulatedExecutor(), DoorVisitorEvaluator(), trace_recorder=recorder)
    task = engine.submit_command(task_spec)
    events_by_step: dict[int, list[dict[str, Any]]] = {}
    for event in definition.events:
        events_by_step.setdefault(int(event["before_step"]), []).append(event)

    while not task.is_terminal:
        for event in events_by_step.get(task.step_count, []):
            _apply_event(event, engine)
            recorder.record_external_event(name=event["type"], details=event, world=world, task=task)
        if task.is_terminal:
            break
        engine.tick()

    post_terminal_observation = None
    post_terminal_world_before = None
    if definition.expected.get("post_terminal_tick_code"):
        post_terminal_world_before = world.snapshot()
        post_terminal_observation = engine.tick()

    write_episode_summary(report_path, task=task, world=world, trace_path=trace_path)
    failures = _evaluate_expected(
        definition,
        engine,
        recorder,
        policy.contexts,
        post_terminal_observation=post_terminal_observation,
        post_terminal_world_before=post_terminal_world_before,
    )
    observations = task.observations
    hard_violation_count = sum(1 for obs in observations if obs.success and obs.action.name == "open")
    categories = _failure_categories(task)
    return ScenarioResult(
        scenario_id=definition.scenario_id,
        passed=not failures,
        status=task.status.value,
        terminal_reason=task.terminal_reason,
        steps=task.step_count,
        rejection_count=sum(1 for obs in observations if obs.source == "gateway"),
        execution_failure_count=sum(1 for obs in observations if obs.source == "executor" and not obs.success),
        hard_violation_count=hard_violation_count,
        trace_complete=not recorder.validate(),
        trace_path=str(trace_path),
        trace_digest=stable_hash([_stable_record(record) for record in recorder.records]),
        failure_categories=categories,
        failures=tuple(failures),
    )


def run_all(scenario_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    results = [run_scenario(load_scenario(path), output_dir) for path in discover_scenarios(scenario_dir)]
    category_counts: Counter[str] = Counter()
    for result in results:
        category_counts.update(result.failure_categories)
    summary = {
        "schema_version": "wangsheng.summary.v2",
        "scenario_count": len(results),
        "passed": sum(result.passed for result in results),
        "failed": sum(not result.passed for result in results),
        "pass_rate": (sum(result.passed for result in results) / len(results)) if results else 0.0,
        "hard_violation_count": sum(result.hard_violation_count for result in results),
        "trace_incomplete_count": sum(not result.trace_complete for result in results),
        "average_steps": mean(result.steps for result in results) if results else 0.0,
        "failure_classification": {category: category_counts.get(category, 0) for category in FAILURE_CATEGORIES},
        "results": [result.to_dict() for result in results],
    }
    target = Path(output_dir) / "summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _apply_world_overrides(world: WorldState, overrides: dict[str, Any]) -> None:
    if "visitor_claimed_name" in overrides:
        world.visitor_claimed_name = overrides["visitor_claimed_name"]
    if "visitor_responses" in overrides:
        world.visitor_responses = list(overrides["visitor_responses"])
    if "actor_location" in overrides:
        world.actor.location = overrides["actor_location"]
    if "conversation_facts" in overrides:
        world.conversation_facts = list(overrides["conversation_facts"])
    if "memory_events" in overrides:
        world.memory_events = [MemoryEvent.from_dict(item) for item in overrides["memory_events"]]
    if "emotional_residue" in overrides:
        world.emotional_residue = list(overrides["emotional_residue"])
    if "forced_action_results" in overrides:
        world.forced_action_results = {key: list(value) for key, value in overrides["forced_action_results"].items()}
    for object_id, values in overrides.get("objects", {}).items():
        obj = world.objects[object_id]
        if "state" in values:
            obj.state = values["state"]
        obj.properties.update(values.get("properties", {}))
    if "actor_permissions" in overrides:
        world.actor.permissions = set(overrides["actor_permissions"])


def _apply_event(event: dict[str, Any], engine: EpisodeEngine) -> None:
    event_type = event["type"]
    if event_type == "cancel_task":
        engine.cancel_task(event.get("reason", "TASK_CANCELLED"))
    elif event_type == "set_object_state":
        engine.world.objects[event["object_id"]].state = event["state"]
    elif event_type == "set_object_property":
        engine.world.objects[event["object_id"]].properties[event["property"]] = event["value"]
    else:
        raise ValueError(f"Unknown scenario event type: {event_type}")


def _evaluate_dialogue_expected(definition: ScenarioDefinition, world: WorldState, recorder: JsonlTraceRecorder) -> list[str]:
    failures: list[str] = []
    expected = definition.expected
    if expected.get("status", "succeeded") != "succeeded":
        failures.append("dialogue-only scenario must expect succeeded")
    if world.objects["door.front"].state != expected.get("door_state", "closed"):
        failures.append("door state mismatch")
    if expected.get("action_count", 0) != 0:
        failures.append("dialogue-only action_count must be zero")
    failures.extend(recorder.validate())
    return failures


def _evaluate_expected(
    definition: ScenarioDefinition,
    engine: EpisodeEngine,
    recorder: JsonlTraceRecorder,
    contexts: list,
    *,
    post_terminal_observation,
    post_terminal_world_before,
) -> list[str]:
    task = engine.active_task
    assert task is not None
    expected = definition.expected
    failures: list[str] = []
    if task.status.value != expected["status"]:
        failures.append(f"status expected {expected['status']} got {task.status.value}")
    if "terminal_reason" in expected and task.terminal_reason != expected["terminal_reason"]:
        failures.append(f"terminal_reason expected {expected['terminal_reason']} got {task.terminal_reason}")
    if task.step_count != expected.get("steps", task.step_count):
        failures.append(f"steps expected {expected['steps']} got {task.step_count}")
    if engine.world.objects["door.front"].state != expected.get("door_state", "closed"):
        failures.append("door state mismatch")
    observed_codes = [obs.code for obs in task.observations]
    for code in expected.get("must_observe_codes", []):
        if code not in observed_codes:
            failures.append(f"missing observation code {code}")
    for code in expected.get("must_not_observe_codes", []):
        if code in observed_codes:
            failures.append(f"unexpected observation code {code}")
    context_text = json.dumps(
        [{"intent": context.intent, "world": context.world} for context in contexts],
        ensure_ascii=False,
        sort_keys=True,
    )
    for text in expected.get("context_must_contain", []):
        if text not in context_text:
            failures.append(f"context missing {text!r}")
    for text in expected.get("context_must_not_contain", []):
        if text in context_text:
            failures.append(f"context leaked {text!r}")
    expected_post_code = expected.get("post_terminal_tick_code")
    if expected_post_code:
        if post_terminal_observation is None or post_terminal_observation.code != expected_post_code:
            failures.append(f"post-terminal code expected {expected_post_code}")
        if post_terminal_world_before != engine.world.snapshot():
            failures.append("post-terminal tick mutated world")
    if definition.roundtrip_world_before:
        roundtrip = WorldState.from_snapshot(json.loads(json.dumps(engine.world.snapshot(), ensure_ascii=False)))
        if roundtrip.snapshot() != engine.world.snapshot():
            failures.append("world roundtrip mismatch")
    expected_categories = set(expected.get("must_classify", []))
    actual_categories = set(_failure_categories(task))
    if not expected_categories.issubset(actual_categories):
        failures.append(f"failure categories missing {sorted(expected_categories - actual_categories)}")
    failures.extend(recorder.validate())
    return failures


def _failure_categories(task: ActiveTask) -> tuple[str, ...]:
    categories = {
        FAILURE_CATEGORY_BY_CODE.get(observation.code, "other")
        for observation in task.observations
        if not observation.success
    }
    if task.terminal_reason == "MAX_STEPS_EXCEEDED":
        categories.add("max_steps")
        categories.discard("other")
    if task.status is TaskStatus.CANCELLED:
        categories.add("cancelled")
    return tuple(sorted(categories))


def _stable_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in {"timestamp", "duration_ms"}}
