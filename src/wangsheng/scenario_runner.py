from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean
from typing import Any

from .engine import EpisodeEngine
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .models import Action, TaskSpec, TaskStatus
from .policy import ScriptedPolicy
from .scenarios import ALL_TOOLS, door_visitor_world
from .trace import JsonlTraceRecorder, write_episode_summary


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    command: str
    required_report_fact: str | None
    max_steps: int
    allowed_actions: frozenset[str]
    forbidden_actions: frozenset[str]
    hard_constraints: frozenset[str]
    world: dict[str, Any]
    actions: tuple[Action, ...]
    events: tuple[dict[str, Any], ...]
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
            "failures": list(self.failures),
        }


def load_scenario(path: str | Path) -> ScenarioDefinition:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    task = payload["task"]
    return ScenarioDefinition(
        scenario_id=payload["scenario_id"],
        command=task["command"],
        required_report_fact=task.get("required_report_fact"),
        max_steps=task.get("max_steps", 12),
        allowed_actions=frozenset(task.get("allowed_actions", sorted(ALL_TOOLS))),
        forbidden_actions=frozenset(task.get("forbidden_actions", [])),
        hard_constraints=frozenset(task.get("hard_constraints", [])),
        world=payload.get("world", {}),
        actions=tuple(Action(item["name"], item.get("target"), item.get("parameters", {})) for item in payload["scripted_actions"]),
        events=tuple(payload.get("events", [])),
        expected=payload["expected"],
    )


def discover_scenarios(directory: str | Path) -> list[Path]:
    return sorted(Path(directory).glob("*.json"))


def run_scenario(definition: ScenarioDefinition, output_dir: str | Path) -> ScenarioResult:
    output = Path(output_dir)
    trace_path = output / "traces" / f"{definition.scenario_id}.jsonl"
    report_path = output / "reports" / f"{definition.scenario_id}.json"
    world = door_visitor_world()
    _apply_world_overrides(world, definition.world)
    task_spec = TaskSpec(
        definition.scenario_id,
        definition.command,
        definition.allowed_actions,
        definition.forbidden_actions,
        definition.required_report_fact,
        definition.hard_constraints,
        definition.max_steps,
    )
    recorder = JsonlTraceRecorder(trace_path, definition.scenario_id)
    engine = EpisodeEngine(world, ScriptedPolicy(list(definition.actions)), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator(), trace_recorder=recorder)
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

    write_episode_summary(report_path, task=task, world=world, trace_path=trace_path)
    failures = _evaluate_expected(definition, engine, recorder)
    observations = task.observations
    hard_violation_count = sum(1 for obs in observations if obs.success and obs.action.name == "open")
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
        failures=tuple(failures),
    )


def run_all(scenario_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    results = [run_scenario(load_scenario(path), output_dir) for path in discover_scenarios(scenario_dir)]
    summary = {
        "schema_version": "wangsheng.summary.v1",
        "scenario_count": len(results),
        "passed": sum(result.passed for result in results),
        "failed": sum(not result.passed for result in results),
        "pass_rate": (sum(result.passed for result in results) / len(results)) if results else 0.0,
        "hard_violation_count": sum(result.hard_violation_count for result in results),
        "trace_incomplete_count": sum(not result.trace_complete for result in results),
        "average_steps": mean(result.steps for result in results) if results else 0.0,
        "results": [result.to_dict() for result in results],
    }
    target = Path(output_dir) / "summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _apply_world_overrides(world, overrides: dict[str, Any]) -> None:
    if "visitor_claimed_name" in overrides:
        world.visitor_claimed_name = overrides["visitor_claimed_name"]
    if "visitor_responses" in overrides:
        world.visitor_responses = list(overrides["visitor_responses"])
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


def _evaluate_expected(definition: ScenarioDefinition, engine: EpisodeEngine, recorder: JsonlTraceRecorder) -> list[str]:
    task = engine.active_task
    assert task is not None
    expected = definition.expected
    failures: list[str] = []
    if task.status.value != expected["status"]:
        failures.append(f"status expected {expected['status']} got {task.status.value}")
    if "terminal_reason" in expected and task.terminal_reason != expected["terminal_reason"]:
        failures.append(f"terminal_reason expected {expected['terminal_reason']} got {task.terminal_reason}")
    if engine.world.objects["door.front"].state != expected.get("door_state", "closed"):
        failures.append("door state mismatch")
    observed_codes = [obs.code for obs in task.observations]
    for code in expected.get("must_observe_codes", []):
        if code not in observed_codes:
            failures.append(f"missing observation code {code}")
    if recorder.validate():
        failures.extend(recorder.validate())
    return failures
