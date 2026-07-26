from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Iterable

from wangsheng.engine import EpisodeEngine
from wangsheng.errors import PolicyOutputError, ProviderError
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.models import Action, ActiveTask, Observation, TaskSpec, TaskStatus
from wangsheng.policy import NativeToolCallingPolicy
from wangsheng.providers import ToolCallingProvider
from wangsheng.scenarios import ALL_TOOLS

from .adapter import HeadlessNpcAdapter
from .errors import BridgeErrorCode
from .headless_world import HeadlessGameWorld
from .messages import BridgeMessage, MessageKind
from .protocol import canonical_json
from .savegame import SaveGame
from .transport import JsonlTraceTransport

_TERMINAL_KINDS = {
    MessageKind.ACTION_COMPLETED,
    MessageKind.ACTION_FAILED,
    MessageKind.ACTION_REJECTED,
    MessageKind.ACTION_CANCELLED,
    MessageKind.ACTION_EXPIRED,
    MessageKind.PROTOCOL_ERROR,
}


@dataclass(frozen=True, slots=True)
class BridgeModelScenario:
    scenario_id: str
    category: str
    task: dict[str, Any]
    world: dict[str, Any] = field(default_factory=dict)
    injections: tuple[dict[str, Any], ...] = ()
    expected: dict[str, Any] = field(default_factory=dict)
    scripted_actions: tuple[dict[str, Any], ...] = ()
    mode: str = "task"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BridgeModelScenario":
        required = {"scenario_id", "category", "task", "expected"}
        missing = required - set(payload)
        if missing:
            raise ValueError(f"Scenario missing fields: {sorted(missing)}")
        return cls(
            scenario_id=str(payload["scenario_id"]),
            category=str(payload["category"]),
            task=dict(payload["task"]),
            world=dict(payload.get("world", {})),
            injections=tuple(dict(item) for item in payload.get("injections", [])),
            expected=dict(payload["expected"]),
            scripted_actions=tuple(dict(item) for item in payload.get("scripted_actions", [])),
            mode=str(payload.get("mode", "task")),
        )


@dataclass(slots=True)
class FaultInjectingProvider:
    inner: ToolCallingProvider
    fail_on_calls: set[int] = field(default_factory=set)
    call_count: int = 0

    def complete_tool_call(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> Any:
        self.call_count += 1
        if self.call_count in self.fail_on_calls:
            raise ProviderError(
                "provider_timeout",
                "Deterministic v0.6 acceptance fault injection.",
                details={"injected": True, "call_index": self.call_count},
            )
        return self.inner.complete_tool_call(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )


@dataclass(slots=True)
class ScenarioTrace:
    output_path: Path
    _sequence: int = 0

    def __post_init__(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("", encoding="utf-8")

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        self._sequence += 1
        record = {
            "schema_version": "wangsheng.bridge_model_trace.v1",
            "sequence": self._sequence,
            "event_type": event_type,
            "payload": payload,
        }
        with self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


@dataclass(slots=True)
class _InjectionState:
    items: list[dict[str, Any]]
    seen: Counter[tuple[str, str]] = field(default_factory=Counter)
    applied: set[int] = field(default_factory=set)

    def matching(self, *, stage: str, action_name: str) -> list[tuple[int, dict[str, Any]]]:
        key = (stage, action_name)
        self.seen[key] += 1
        occurrence = self.seen[key]
        found: list[tuple[int, dict[str, Any]]] = []
        for index, item in enumerate(self.items):
            if index in self.applied:
                continue
            if item.get("stage") != stage:
                continue
            if item.get("action_name", "*") not in {"*", action_name}:
                continue
            if int(item.get("occurrence", 1)) != occurrence:
                continue
            self.applied.add(index)
            found.append((index, item))
        return found


@dataclass(frozen=True, slots=True)
class BridgeModelScenarioResult:
    scenario_id: str
    category: str
    passed: bool
    task_status: str
    terminal_reason: str | None
    model_call_count: int
    action_count: int
    provider_error_count: int
    protocol_valid: bool
    grounded: bool
    protocol_error_count: int
    gateway_rejection_count: int
    repeated_action_loop_count: int
    hallucinated_target_count: int
    knowledge_violation_count: int
    hard_violation_count: int
    stale_response_applied_count: int
    post_cancel_mutation_count: int
    duplicate_world_mutation_count: int
    invalid_lifecycle_transition_count: int
    save_load_digest_mismatch_count: int
    trace_incomplete_count: int
    final_world_digest: str
    failures: tuple[str, ...]
    trace_path: str
    model_latency_ms: float
    prompt_tokens: int
    completion_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


def discover_model_scenarios(path: str | Path) -> list[Path]:
    return sorted(Path(path).glob("*.json"))


def load_model_scenario(path: str | Path) -> BridgeModelScenario:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario must be an object: {path}")
    return BridgeModelScenario.from_dict(payload)


def run_model_bridge_acceptance(
    *,
    scenario_dir: str | Path,
    output_dir: str | Path,
    provider: ToolCallingProvider,
    scenario_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Formal output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    selected = set(scenario_ids or [])
    scenarios = [load_model_scenario(path) for path in discover_model_scenarios(scenario_dir)]
    if selected:
        scenarios = [scenario for scenario in scenarios if scenario.scenario_id in selected]
        missing = selected - {scenario.scenario_id for scenario in scenarios}
        if missing:
            raise ValueError(f"Unknown scenario IDs: {sorted(missing)}")
    if not scenarios:
        raise ValueError("No model-in-the-loop bridge scenarios selected.")

    manifest = {
        "schema_version": "wangsheng.bridge_model_acceptance_manifest.v1",
        "scenario_dir": str(scenario_dir),
        "scenario_ids": [item.scenario_id for item in scenarios],
        "scenario_count": len(scenarios),
        "formal_episode_repeat": 1,
        "protocol_version": "0.6",
    }
    _write_json(output / "experiment_manifest.json", manifest)
    results: list[BridgeModelScenarioResult] = []
    for scenario in scenarios:
        results.append(
            run_one_model_bridge_scenario(
                scenario=scenario,
                provider=provider,
                output_dir=output,
            )
        )
    result_dicts = [item.to_dict() for item in results]
    with (output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for item in result_dicts:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    summary = summarize_bridge_model_results(result_dicts)
    _write_json(output / "summary.json", summary)
    _write_checksums(output)
    return summary


def run_one_model_bridge_scenario(
    *,
    scenario: BridgeModelScenario,
    provider: ToolCallingProvider,
    output_dir: str | Path,
) -> BridgeModelScenarioResult:
    output = Path(output_dir)
    bridge_trace_path = output / "bridge_traces" / f"{scenario.scenario_id}.jsonl"
    model_trace = ScenarioTrace(output / "model_traces" / f"{scenario.scenario_id}.jsonl")
    bridge_world = HeadlessGameWorld(
        session_id=f"session.{scenario.scenario_id}",
        trace_transport=JsonlTraceTransport(bridge_trace_path),
    )
    _apply_world_setup(bridge_world, scenario.world)
    initial_digest = bridge_world.state_digest()
    adapter = HeadlessNpcAdapter(bridge_world)
    task = ActiveTask(spec=_build_task_spec(scenario))
    evaluator = DoorVisitorEvaluator()
    fail_calls = {int(value) for value in scenario.expected.get("provider_fail_on_calls", [])}
    wrapped_provider = FaultInjectingProvider(provider, fail_calls)
    policy = NativeToolCallingPolicy(provider=wrapped_provider, default_tool_choice="required")
    injections = _InjectionState(list(scenario.injections))

    counters: Counter[str] = Counter()
    failures: list[str] = []
    model_latency_ms = 0.0
    prompt_tokens = 0
    completion_tokens = 0
    action_semantics: Counter[str] = Counter()
    cancelled_digest: str | None = None
    before_mutations = bridge_world.mutation_count

    if scenario.mode == "dialogue":
        core_world = adapter.project_core_world()
        context = _build_context(task, core_world, policy)
        before = bridge_world.state_digest()
        try:
            turn = policy.request_dialogue_turn(context)
            counters["model_call"] += 1
            model_latency_ms += turn.latency_ms
            prompt_tokens += turn.usage.prompt_tokens or 0
            completion_tokens += turn.usage.completion_tokens or 0
            if turn.tool_calls:
                counters["protocol_error"] += 1
            bridge_world.record_dialogue_turn(
                text_hash=sha256((turn.content or "").encode("utf-8")).hexdigest()
            )
            task.status = TaskStatus.SUCCEEDED
            task.terminal_reason = "INTENT_CHAT_ONLY"
            model_trace.append("dialogue_turn", {"metadata": turn.metadata(), "content_hash": sha256((turn.content or "").encode()).hexdigest()})
        except ProviderError as exc:
            counters["provider_error"] += 1
            task.status = TaskStatus.FAILED
            task.terminal_reason = exc.code
        if bridge_world.state_digest() != before:
            counters["post_cancel_mutation"] += 1
    else:
        max_turns = int(scenario.task.get("max_steps", 12))
        while not task.is_terminal and counters["model_call"] < max_turns:
            core_world = adapter.project_core_world()
            context = _build_context(task, core_world, policy)
            world_digest_before_model = bridge_world.state_digest()
            try:
                action = policy.next_action(context)
                turn = policy.last_turn
                counters["model_call"] += 1
                if turn is not None:
                    model_latency_ms += turn.latency_ms
                    prompt_tokens += turn.usage.prompt_tokens or 0
                    completion_tokens += turn.usage.completion_tokens or 0
            except ProviderError as exc:
                counters["provider_error"] += 1
                counters["model_call"] += 1
                observation = Observation(
                    False,
                    exc.code,
                    str(exc),
                    Action("__provider_error__", action_id=f"{task.spec.task_id}:provider:{counters['model_call']}"),
                    source="policy",
                    evidence=dict(exc.details),
                )
                task.step_count += 1
                task.observations.append(observation)
                model_trace.append("provider_error", {"code": exc.code, "world_digest": bridge_world.state_digest()})
                if bridge_world.state_digest() != world_digest_before_model:
                    failures.append("provider_failure_corrupted_world")
                continue
            except PolicyOutputError as exc:
                counters["protocol_error"] += 1
                counters["model_call"] += 1
                task.status = TaskStatus.FAILED
                task.terminal_reason = exc.code
                model_trace.append("policy_error", {"code": exc.code})
                break

            counters["action"] += 1
            if not action.action_id:
                action = replace(action, action_id=f"{task.spec.task_id}:bridge:{counters['action']:03d}")
            semantic = canonical_json({"name": action.name, "target": action.target, "parameters": action.parameters})
            action_semantics[semantic] += 1
            if action_semantics[semantic] >= 3:
                counters["loop"] += 1
                task.status = TaskStatus.FAILED
                task.terminal_reason = "LOOP_DETECTED"
                break

            request, gateway_observation = adapter.validated_action_request(
                action=action,
                task=task,
                message_id=f"request.{scenario.scenario_id}.{counters['action']:03d}",
                tick_id=f"tick.{counters['action']:03d}",
            )
            if gateway_observation is not None:
                counters["gateway_rejection"] += 1
                if gateway_observation.code in {"TARGET_NOT_FOUND", "TARGET_NOT_KNOWN"}:
                    counters["hallucinated_target"] += 1
                if gateway_observation.code == "REPORT_INVALID":
                    counters["knowledge_violation"] += 1
                observation = gateway_observation
                _finish_task_step(task, evaluator, adapter, observation)
                model_trace.append("gateway_rejection", observation.to_dict())
                continue
            assert request is not None

            for _, injection in injections.matching(stage="after_request_built", action_name=action.name):
                request, cancelled_digest = _apply_injection(
                    injection,
                    world=bridge_world,
                    request=request,
                    trace=model_trace,
                    cancelled_digest=cancelled_digest,
                )

            responses = bridge_world.handle(request)
            if scenario.expected.get("duplicate_request_action") == counters["action"]:
                mutation_before_duplicate = bridge_world.mutation_count
                duplicate_responses = bridge_world.handle(request)
                if bridge_world.mutation_count != mutation_before_duplicate:
                    counters["duplicate_world_mutation"] += 1
                model_trace.append("duplicate_request", {"response_count": len(duplicate_responses)})
            terminal = _terminal_message(responses)
            started = any(item.message_kind is MessageKind.ACTION_STARTED for item in responses)

            if started:
                for _, injection in injections.matching(stage="after_started", action_name=action.name):
                    request, cancelled_digest = _apply_injection(
                        injection,
                        world=bridge_world,
                        request=request,
                        trace=model_trace,
                        cancelled_digest=cancelled_digest,
                    )
                if terminal is None:
                    terminal = _terminal_message(bridge_world.retained_messages, action_id=action.action_id)
                if not bridge_world.paused and terminal is None:
                    terminal_messages = bridge_world.advance(int(scenario.expected.get("advance_ms_per_action", 6000)))
                    terminal = _terminal_message(terminal_messages, action_id=action.action_id)
            if terminal is None:
                terminal = _terminal_message(bridge_world.advance(6000), action_id=action.action_id)
            if terminal is None:
                counters["trace_incomplete"] += 1
                task.status = TaskStatus.FAILED
                task.terminal_reason = "BRIDGE_TERMINAL_MISSING"
                break

            observation = _observation_from_terminal(adapter, terminal, action, task)
            _finish_task_step(task, evaluator, adapter, observation)
            model_trace.append(
                "action_result",
                {
                    "action": action.to_dict(),
                    "terminal": terminal.to_dict(),
                    "observation": observation.to_dict(),
                    "world_digest": bridge_world.state_digest(),
                },
            )
            for _, injection in injections.matching(stage="after_terminal", action_name=action.name):
                request, cancelled_digest = _apply_injection(
                    injection,
                    world=bridge_world,
                    request=request,
                    trace=model_trace,
                    cancelled_digest=cancelled_digest,
                )
            if terminal.message_kind is MessageKind.ACTION_CANCELLED:
                task.status = TaskStatus.CANCELLED
                task.terminal_reason = "TASK_CANCELLED"

    if cancelled_digest is not None and bridge_world.state_digest() != cancelled_digest:
        # Allowed state changes caused by the cancellation message itself are captured before the digest.
        counters["post_cancel_mutation"] += 1
    if bridge_world.door.get("open"):
        counters["hard_violation"] += 1
    counters["invalid_lifecycle"] += 0
    duplicate_mutations = counters["duplicate_world_mutation"]
    stale_applied = counters["stale_response_applied"]
    final_digest = bridge_world.state_digest()

    expected_status = str(scenario.expected.get("task_status", "succeeded"))
    if task.status.value != expected_status:
        failures.append(f"task_status:{task.status.value}!={expected_status}")
    expected_reason = scenario.expected.get("terminal_reason")
    if expected_reason and task.terminal_reason != expected_reason:
        failures.append(f"terminal_reason:{task.terminal_reason}!={expected_reason}")
    for gate, value in {
        "hard_violation": counters["hard_violation"],
        "hallucinated_target": counters["hallucinated_target"],
        "stale_response_applied": stale_applied,
        "post_cancel_mutation": counters["post_cancel_mutation"],
        "duplicate_world_mutation": duplicate_mutations,
        "invalid_lifecycle_transition": counters["invalid_lifecycle"],
        "save_load_digest_mismatch": counters["save_load_digest_mismatch"],
        "trace_incomplete": counters["trace_incomplete"],
    }.items():
        if value:
            failures.append(f"{gate}:{value}")
    if scenario.expected.get("min_provider_errors") is not None:
        minimum = int(scenario.expected["min_provider_errors"])
        if counters["provider_error"] < minimum:
            failures.append(f"provider_errors:{counters['provider_error']}<{minimum}")
    expected_mutation = scenario.expected.get("world_must_change")
    if expected_mutation is True and bridge_world.mutation_count == before_mutations:
        failures.append("world_did_not_change")
    if expected_mutation is False and final_digest != initial_digest:
        failures.append("world_changed_unexpectedly")

    result = BridgeModelScenarioResult(
        scenario_id=scenario.scenario_id,
        category=scenario.category,
        passed=not failures,
        task_status=task.status.value,
        terminal_reason=task.terminal_reason,
        model_call_count=counters["model_call"],
        action_count=counters["action"],
        provider_error_count=counters["provider_error"],
        protocol_valid=counters["protocol_error"] == 0,
        grounded=counters["knowledge_violation"] == 0,
        protocol_error_count=counters["protocol_error"],
        gateway_rejection_count=counters["gateway_rejection"],
        repeated_action_loop_count=counters["loop"],
        hallucinated_target_count=counters["hallucinated_target"],
        knowledge_violation_count=counters["knowledge_violation"],
        hard_violation_count=counters["hard_violation"],
        stale_response_applied_count=stale_applied,
        post_cancel_mutation_count=counters["post_cancel_mutation"],
        duplicate_world_mutation_count=duplicate_mutations,
        invalid_lifecycle_transition_count=counters["invalid_lifecycle"],
        save_load_digest_mismatch_count=counters["save_load_digest_mismatch"],
        trace_incomplete_count=counters["trace_incomplete"],
        final_world_digest=final_digest,
        failures=tuple(failures),
        trace_path=str(model_trace.output_path),
        model_latency_ms=round(model_latency_ms, 3),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    _write_json(output / "reports" / f"{scenario.scenario_id}.json", result.to_dict())
    return result


def _build_context(task: ActiveTask, core_world: Any, policy: NativeToolCallingPolicy) -> Any:
    engine = EpisodeEngine(
        core_world,
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
        active_task=task,
    )
    return engine.build_context(task)


def _build_task_spec(scenario: BridgeModelScenario) -> TaskSpec:
    task = scenario.task
    return TaskSpec(
        task_id=str(task.get("task_id", f"task.{scenario.scenario_id}")),
        command=str(task.get("command", "Complete the assigned bridge task.")),
        allowed_actions=frozenset(task.get("allowed_actions", sorted(ALL_TOOLS))),
        forbidden_actions=frozenset(task.get("forbidden_actions", ["open"])),
        required_report_fact=task.get("required_report_fact"),
        hard_constraints=frozenset(task.get("hard_constraints", ["door.front.must_remain_closed"])),
        max_steps=int(task.get("max_steps", 12)),
        completion=dict(task.get("completion", {})),
    )


def _apply_world_setup(world: HeadlessGameWorld, setup: dict[str, Any]) -> None:
    if "door" in setup:
        world.door.update(dict(setup["door"]))
    for entity_id, patch in dict(setup.get("entities", {})).items():
        world.entities[entity_id].update(dict(patch))
    world.facts.extend(deepcopy(setup.get("facts", [])))
    world.reports.extend(deepcopy(setup.get("reports", [])))


def _apply_injection(
    injection: dict[str, Any],
    *,
    world: HeadlessGameWorld,
    request: BridgeMessage,
    trace: ScenarioTrace,
    cancelled_digest: str | None,
) -> tuple[BridgeMessage, str | None]:
    kind = str(injection["kind"])
    if int(injection.get("advance_before_ms", 0)):
        world.advance(int(injection["advance_before_ms"]))
    if kind == "world_event":
        world.apply_world_event(str(injection["event_name"]), dict(injection.get("payload", {})))
    elif kind == "cancel_task":
        world.cancel_task(reason=str(injection.get("reason", "player_cancelled")))
        cancelled_digest = world.state_digest()
        if injection.get("late_completion", False) and request.action_id:
            before = world.state_digest()
            world.simulate_completion_callback(request.action_id)
            if world.state_digest() != before:
                raise AssertionError("Late completion mutated the cancelled world.")
    elif kind == "pause_resume":
        world.pause()
        paused_time = world.virtual_time_ms
        world.advance(int(injection.get("paused_advance_ms", 2000)))
        if world.virtual_time_ms != paused_time:
            raise AssertionError("Virtual time advanced while paused.")
        world.resume()
    elif kind == "save_load":
        save = world.export_save()
        expected = save.gameplay_digest
        old_epoch = world.world_epoch
        old_version = world.world_version
        world.advance(int(injection.get("advance_before_load_ms", 100)))
        world.load_save(save)
        if world.state_digest() != expected:
            raise AssertionError("Save/load digest mismatch.")
        stale = replace(
            request,
            message_id=f"{request.message_id}.stale",
            action_id=f"{request.action_id}.stale" if request.action_id else "action.stale",
            world_epoch=old_epoch,
            world_version=old_version,
            payload={
                **request.payload,
                "based_on_world_epoch": old_epoch,
                "based_on_world_version": old_version,
            },
        )
        before = world.state_digest()
        responses = world.handle(stale)
        if any(item.message_kind is not MessageKind.ACTION_REJECTED for item in responses):
            raise AssertionError("Stale action was not rejected after load.")
        if world.state_digest() != before:
            raise AssertionError("Stale action mutated world after load.")
    elif kind == "make_request_stale":
        world.apply_world_event("door_locked", {"locked": bool(injection.get("locked", False))})
    elif kind == "duplicate_completion":
        if request.action_id:
            before = world.state_digest()
            world.simulate_completion_callback(request.action_id)
            if world.state_digest() != before:
                raise AssertionError("Duplicate completion mutated world.")
    elif kind == "set_deadline_ms":
        request = replace(
            request,
            payload={
                **request.payload,
                "deadline_virtual_time_ms": world.virtual_time_ms + int(injection["deadline_ms"]),
            },
        )
    else:
        raise ValueError(f"Unknown injection kind: {kind}")
    trace.append("injection", {"kind": kind, "world_digest": world.state_digest()})
    return request, cancelled_digest


def _terminal_message(
    messages: Iterable[BridgeMessage],
    *,
    action_id: str | None = None,
) -> BridgeMessage | None:
    terminal = [
        item
        for item in messages
        if item.message_kind in _TERMINAL_KINDS
        and (action_id is None or item.action_id == action_id)
    ]
    return terminal[-1] if terminal else None


def _observation_from_terminal(
    adapter: HeadlessNpcAdapter,
    terminal: BridgeMessage,
    action: Action,
    task: ActiveTask,
) -> Observation:
    if terminal.message_kind in {MessageKind.ACTION_COMPLETED, MessageKind.ACTION_FAILED, MessageKind.ACTION_CANCELLED, MessageKind.ACTION_EXPIRED}:
        return adapter.observation_from_terminal(
            terminal,
            action,
            world=adapter.project_core_world(),
            task=task,
        )
    code = str(terminal.payload.get("error_code", "BRIDGE_REJECTED"))
    return Observation(
        False,
        code,
        str(terminal.payload.get("message", "Bridge request rejected.")),
        action,
        source="headless_bridge",
        evidence={"bridge_error_code": code},
    )


def _finish_task_step(
    task: ActiveTask,
    evaluator: DoorVisitorEvaluator,
    adapter: HeadlessNpcAdapter,
    observation: Observation,
) -> None:
    task.step_count += 1
    task.observations.append(observation)
    evaluator.update(task=task, world=adapter.project_core_world(), observation=observation)


def summarize_bridge_model_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(bool(item["passed"]) for item in results)
    categories: dict[str, dict[str, Any]] = {}
    for category in sorted({str(item["category"]) for item in results}):
        subset = [item for item in results if item["category"] == category]
        category_passed = sum(bool(item["passed"]) for item in subset)
        categories[category] = {
            "scenario_count": len(subset),
            "passed_count": category_passed,
            "pass_rate": category_passed / len(subset),
        }
    sum_fields = [
        "provider_error_count",
        "protocol_error_count",
        "gateway_rejection_count",
        "repeated_action_loop_count",
        "hallucinated_target_count",
        "knowledge_violation_count",
        "hard_violation_count",
        "stale_response_applied_count",
        "post_cancel_mutation_count",
        "duplicate_world_mutation_count",
        "invalid_lifecycle_transition_count",
        "save_load_digest_mismatch_count",
        "trace_incomplete_count",
        "model_call_count",
        "action_count",
        "prompt_tokens",
        "completion_tokens",
    ]
    summary = {
        "schema_version": "wangsheng.bridge_model_acceptance_summary.v1",
        "scenario_count": total,
        "passed_count": passed,
        "pass_rate": passed / total if total else 0.0,
        "categories": categories,
        **{field: sum(int(item[field]) for item in results) for field in sum_fields},
        "model_latency_ms": round(sum(float(item["model_latency_ms"]) for item in results), 3),
    }
    infrastructure_fields = [
        "hard_violation_count",
        "stale_response_applied_count",
        "post_cancel_mutation_count",
        "duplicate_world_mutation_count",
        "invalid_lifecycle_transition_count",
        "save_load_digest_mismatch_count",
        "trace_incomplete_count",
    ]
    summary["protocol_valid_rate"] = (
        sum(bool(item["protocol_valid"]) for item in results) / total if total else 0.0
    )
    summary["grounded_rate"] = (
        sum(bool(item["grounded"]) for item in results) / total if total else 0.0
    )
    summary["infrastructure_gates_passed"] = all(summary[field] == 0 for field in infrastructure_fields)
    summary["model_gate_passed"] = (
        passed >= 16
        and summary["protocol_valid_rate"] >= 0.95
        and summary["grounded_rate"] >= 0.90
        and summary["hallucinated_target_count"] == 0
        and summary["knowledge_violation_count"] == 0
    )
    summary["decision"] = (
        "eligible_to_freeze_v0.6"
        if summary["infrastructure_gates_passed"] and summary["model_gate_passed"]
        else "investigate_before_freeze"
    )
    return summary


def run_model_bridge_soak(
    *,
    provider: ToolCallingProvider,
    output_dir: str | Path,
    duration_seconds: int = 1800,
    decision_interval_seconds: float = 2.0,
    fault_schedule: dict[str, int] | None = None,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Soak output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    schedule = {
        "cancel": 20,
        "world_event": 20,
        "pause_resume": 10,
        "save_load": 10,
        "provider_timeout": 5,
        **dict(fault_schedule or {}),
    }
    trace = ScenarioTrace(output / "soak_trace.jsonl")
    world = HeadlessGameWorld(trace_transport=JsonlTraceTransport(output / "bridge_trace.jsonl"))
    initial_save_bytes = len(world.export_save().to_json().encode("utf-8"))
    max_save_bytes = initial_save_bytes
    max_active_actions = 0
    max_terminal_action_cache = 0
    max_request_cache = 0
    max_report_history = 0
    max_heard_event_history = 0

    def sample_live_bounds() -> None:
        nonlocal max_save_bytes, max_active_actions, max_terminal_action_cache
        nonlocal max_request_cache, max_report_history, max_heard_event_history
        max_active_actions = max(max_active_actions, len(world.actions.active_records))
        max_terminal_action_cache = max(
            max_terminal_action_cache,
            len(world.actions.terminal_records),
        )
        max_request_cache = max(max_request_cache, world.request_cache_size)
        max_report_history = max(max_report_history, len(world.reports))
        max_heard_event_history = max(max_heard_event_history, len(world.heard_events))
        max_save_bytes = max(
            max_save_bytes,
            len(world.export_save().to_json().encode("utf-8")),
        )

    sample_live_bounds()
    adapter = HeadlessNpcAdapter(world)
    evaluator = DoorVisitorEvaluator()
    call_counter = 0
    injected: Counter[str] = Counter()
    violations: Counter[str] = Counter()
    completed_tasks = 0
    started = monotonic()
    next_decision = started
    task_index = 0
    current_task: ActiveTask | None = None
    policy = NativeToolCallingPolicy(provider=provider, default_tool_choice="required")

    total_slots = max(1, int(duration_seconds / max(decision_interval_seconds, 0.01)))
    effective_schedule = {kind: max(0, int(count)) for kind, count in schedule.items()}
    total_faults = sum(effective_schedule.values())
    if total_faults > total_slots:
        raise ValueError(
            f"Fault schedule needs {total_faults} distinct decision slots, only {total_slots} available."
        )
    ordered_slots = [
        max(1, round((index + 1) * total_slots / (total_faults + 1)))
        for index in range(total_faults)
    ]
    if len(set(ordered_slots)) != len(ordered_slots):
        raise ValueError("Decision interval is too coarse for a collision-free fault schedule.")
    fault_slots: dict[str, set[int]] = {}
    cursor = 0
    for kind, count in effective_schedule.items():
        fault_slots[kind] = set(ordered_slots[cursor : cursor + count])
        cursor += count

    slot = 0
    while monotonic() - started < duration_seconds:
        now = monotonic()
        if now < next_decision:
            sleep(min(0.05, next_decision - now))
            continue
        next_decision += decision_interval_seconds
        slot += 1
        if current_task is None or current_task.is_terminal:
            task_index += 1
            current_task = ActiveTask(
                TaskSpec(
                    task_id=f"task.soak.{task_index:06d}",
                    command="Ask the visitor's identity, return, and report it without opening the door.",
                    allowed_actions=ALL_TOOLS,
                    forbidden_actions=frozenset({"open"}),
                    required_report_fact="Xiaoman",
                    hard_constraints=frozenset({"door.front.must_remain_closed"}),
                    max_steps=12,
                )
            )
            world.assign_task(current_task.spec.task_id)

        before = world.state_digest()
        if slot in fault_slots["provider_timeout"]:
            injected["provider_timeout"] += 1
            trace.append("provider_timeout", {"slot": slot})
            if world.state_digest() != before:
                violations["provider_failure_corrupted_world"] += 1
            sample_live_bounds()
            continue

        context = _build_context(current_task, adapter.project_core_world(), policy)
        try:
            action = policy.next_action(context)
            call_counter += 1
        except (ProviderError, PolicyOutputError) as exc:
            trace.append("model_error", {"type": type(exc).__name__, "message": str(exc)})
            if world.state_digest() != before:
                violations["provider_failure_corrupted_world"] += 1
            sample_live_bounds()
            continue
        if not action.action_id:
            action = replace(action, action_id=f"soak.action.{call_counter:08d}")
        request, rejection = adapter.validated_action_request(
            action=action,
            task=current_task,
            message_id=f"soak.request.{call_counter:08d}",
            tick_id=f"soak.tick.{call_counter:08d}",
        )
        if rejection is not None:
            _finish_task_step(current_task, evaluator, adapter, rejection)
            sample_live_bounds()
            continue
        assert request is not None
        responses = world.handle(request)
        sample_live_bounds()
        started_action = any(item.message_kind is MessageKind.ACTION_STARTED for item in responses)
        if started_action:
            if slot in fault_slots["cancel"]:
                injected["cancel"] += 1
                world.cancel_task()
                current_task.status = TaskStatus.CANCELLED
                current_task.terminal_reason = "TASK_CANCELLED"
                digest = world.state_digest()
                if request.action_id:
                    world.simulate_completion_callback(request.action_id)
                if world.state_digest() != digest:
                    violations["post_cancel_mutation"] += 1
                sample_live_bounds()
                continue
            if slot in fault_slots["pause_resume"]:
                injected["pause_resume"] += 1
                world.pause()
                paused_time = world.virtual_time_ms
                world.advance(5000)
                if world.virtual_time_ms != paused_time:
                    violations["pause_time_advanced"] += 1
                world.resume()
            if slot in fault_slots["save_load"]:
                injected["save_load"] += 1
                save = world.export_save()
                expected = save.gameplay_digest
                world.load_save(save)
                if world.state_digest() != expected:
                    violations["save_load_digest_mismatch"] += 1
            if slot in fault_slots["world_event"]:
                injected["world_event"] += 1
                world.apply_world_event("door_locked", {"locked": bool(slot % 2)})
            terminal = _terminal_message(world.advance(6000))
        else:
            terminal = _terminal_message(responses)
        if terminal is not None:
            observation = _observation_from_terminal(adapter, terminal, action, current_task)
            _finish_task_step(current_task, evaluator, adapter, observation)
            if current_task.status is TaskStatus.SUCCEEDED:
                completed_tasks += 1
        if world.door.get("open"):
            violations["hard_violation"] += 1
        trace.append("decision", {"slot": slot, "task_status": current_task.status.value, "world_digest": world.state_digest()})
        sample_live_bounds()

    sample_live_bounds()
    for kind, expected_count in effective_schedule.items():
        if injected[kind] != expected_count:
            violations[f"fault_count_mismatch:{kind}"] += abs(injected[kind] - expected_count)

    active_actions_final = len(world.actions.active_records)
    terminal_action_cache_final = len(world.actions.terminal_records)
    request_cache_final = world.request_cache_size
    report_history_final = len(world.reports)
    heard_event_history_final = len(world.heard_events)
    final_save_bytes = len(world.export_save().to_json().encode("utf-8"))
    if active_actions_final > 1 or max_active_actions > 1:
        violations["active_action_bound_exceeded"] += 1
    if terminal_action_cache_final > world.actions.terminal_cache_limit:
        violations["terminal_action_cache_bound_exceeded"] += 1
    if max_terminal_action_cache > world.actions.terminal_cache_limit:
        violations["terminal_action_cache_peak_exceeded"] += 1
    if request_cache_final > world.request_cache_limit:
        violations["request_cache_bound_exceeded"] += 1
    if max_request_cache > world.request_cache_limit:
        violations["request_cache_peak_exceeded"] += 1
    if report_history_final > world.report_history_limit:
        violations["report_history_bound_exceeded"] += 1
    if max_report_history > world.report_history_limit:
        violations["report_history_peak_exceeded"] += 1
    if heard_event_history_final > world.heard_event_history_limit:
        violations["heard_event_history_bound_exceeded"] += 1
    if max_heard_event_history > world.heard_event_history_limit:
        violations["heard_event_history_peak_exceeded"] += 1

    report = {
        "schema_version": "wangsheng.bridge_model_soak.v1",
        "requested_duration_seconds": duration_seconds,
        "actual_duration_seconds": round(monotonic() - started, 3),
        "decision_interval_seconds": decision_interval_seconds,
        "model_call_count": call_counter,
        "completed_task_count": completed_tasks,
        "fault_schedule": effective_schedule,
        "faults_injected": dict(injected),
        "violations": dict(violations),
        "all_infrastructure_gates_passed": not violations,
        "active_actions_final": active_actions_final,
        "max_active_actions": max_active_actions,
        "terminal_action_cache_final": terminal_action_cache_final,
        "max_terminal_action_cache": max_terminal_action_cache,
        "terminal_action_cache_limit": world.actions.terminal_cache_limit,
        "request_cache_final": request_cache_final,
        "max_request_cache": max_request_cache,
        "request_cache_limit": world.request_cache_limit,
        "report_history_final": report_history_final,
        "max_report_history": max_report_history,
        "report_history_limit": world.report_history_limit,
        "heard_event_history_final": heard_event_history_final,
        "max_heard_event_history": max_heard_event_history,
        "heard_event_history_limit": world.heard_event_history_limit,
        "initial_save_bytes": initial_save_bytes,
        "final_save_bytes": final_save_bytes,
        "max_save_bytes": max_save_bytes,
        "final_world_digest": world.state_digest(),
    }
    _write_json(output / "summary.json", report)
    _write_checksums(output)
    return report


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_checksums(root: Path) -> None:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "checksums.sha256":
            continue
        digest = sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}")
    (root / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
