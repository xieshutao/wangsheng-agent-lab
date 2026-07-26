from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import perf_counter

from .errors import PolicyOutputError, ProviderError
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .models import Action, ActiveTask, Observation, PolicyContext, TaskSpec, TaskStatus, WorldState
from .policy import Policy
from .progress import compact_observations, semantic_action_fingerprint
from .reason_codes import ReasonCode
from .reporting import completion_progress, model_visible_reportable_facts
from .trace import JsonlTraceRecorder


@dataclass(slots=True)
class EpisodeEngine:
    world: WorldState
    policy: Policy
    gateway: Gateway
    executor: SimulatedExecutor
    evaluator: DoorVisitorEvaluator
    active_task: ActiveTask | None = None
    trace_recorder: JsonlTraceRecorder | None = None
    loop_repeat_limit: int = 3
    terminal_on_policy_error: bool = False
    terminal_on_provider_error: bool = False
    observation_window: int = 3

    def submit_command(self, spec: TaskSpec) -> ActiveTask:
        if self.active_task is not None and not self.active_task.is_terminal:
            raise RuntimeError("An active task already exists.")
        self.active_task = ActiveTask(spec=spec)
        return self.active_task

    def cancel_task(self, reason: str = "TASK_CANCELLED") -> ActiveTask:
        task = self._require_task()
        if not task.is_terminal:
            task.status = TaskStatus.CANCELLED
            task.terminal_reason = reason
        return task

    def tick(self) -> Observation:
        task = self._require_task()
        if task.is_terminal:
            return Observation(
                False,
                ReasonCode.TASK_TERMINAL.value,
                "No tick after terminal task.",
                Action("wait", parameters={"seconds": 0}),
                source="runtime",
            )

        step = task.step_count
        context = self.build_context(task)
        world_before = self.world.snapshot()
        started = perf_counter()
        gateway_status = "not_reached"

        try:
            proposed = self.policy.next_action(context)
            requested = (
                proposed
                if proposed.action_id
                else replace(proposed, action_id=f"{task.spec.task_id}:a{step + 1:03d}")
            )
            action = self.gateway.canonicalize_action(action=requested, world=self.world)
        except PolicyOutputError as exc:
            observation = Observation(
                False,
                exc.code,
                str(exc),
                Action(
                    "__invalid_model_output__",
                    parameters={"raw_output": exc.raw_output},
                    action_id=f"{task.spec.task_id}:a{step + 1:03d}",
                ),
                source="policy",
            )
            if self.terminal_on_policy_error:
                task.status = TaskStatus.FAILED
                task.terminal_reason = exc.code
        except ProviderError as exc:
            observation = Observation(
                False,
                exc.code,
                str(exc),
                Action(
                    "__provider_error__",
                    parameters={"details": dict(exc.details)},
                    action_id=f"{task.spec.task_id}:a{step + 1:03d}",
                ),
                source="policy",
                evidence=dict(exc.details),
            )
            if self.terminal_on_provider_error:
                task.status = TaskStatus.FAILED
                task.terminal_reason = exc.code
        else:
            fingerprint = semantic_action_fingerprint(action, self.world)
            task.fingerprint_counts[fingerprint] = task.fingerprint_counts.get(fingerprint, 0) + 1
            if task.fingerprint_counts[fingerprint] >= self.loop_repeat_limit:
                observation = Observation(
                    False,
                    ReasonCode.LOOP_DETECTED.value,
                    "A semantically equivalent action was repeated without new world or evidence progress.",
                    action,
                    source="runtime",
                    evidence={
                        "repeat_count": task.fingerprint_counts[fingerprint],
                        "retryable": False,
                        "required_change_before_retry": (
                            "change the selected action or obtain new evidence before retrying"
                        ),
                    },
                )
                task.status = TaskStatus.FAILED
                task.terminal_reason = ReasonCode.LOOP_DETECTED.value
            else:
                rejection = self.gateway.validate(action=action, task=task, world=self.world)
                if rejection is not None:
                    observation = rejection
                    gateway_status = "rejected"
                else:
                    gateway_status = "allowed"
                    observation = self.executor.execute(action=action, world=self.world, task=task)

        task.step_count += 1
        task.observations.append(observation)
        self.evaluator.update(task=task, world=self.world, observation=observation)
        world_after = self.world.snapshot()
        duration_ms = (perf_counter() - started) * 1000
        if self.trace_recorder:
            self.trace_recorder.record_tick(
                step=step,
                context=context,
                observation=observation,
                world_before=world_before,
                world_after=world_after,
                gateway_status=gateway_status,
                duration_ms=duration_ms,
                task=task,
                model_metadata=getattr(self.policy, "last_model_metadata", None),
            )
        return observation

    def run_until_terminal(self) -> ActiveTask:
        task = self._require_task()
        while not task.is_terminal:
            self.tick()
        return task

    def build_context(self, task: ActiveTask) -> PolicyContext:
        allowed = frozenset(
            name for name in task.spec.allowed_actions if self.gateway.registry.get(name)
        )
        recent_observations, history_summary = compact_observations(
            task.observations,
            window=self.observation_window,
        )
        world_payload = self.world.context_snapshot()
        world_payload["reportable_facts"] = model_visible_reportable_facts(self.world, task)
        return PolicyContext(
            command=task.spec.command,
            task_id=task.spec.task_id,
            step_count=task.step_count,
            available_actions=tuple(sorted(allowed)),
            forbidden_actions=tuple(sorted(task.spec.forbidden_actions)),
            world=world_payload,
            observations=recent_observations,
            tool_schemas=self.gateway.registry.function_schemas(allowed),
            intent=task.spec.intent.to_dict() if task.spec.intent else {},
            current_affordances=self.gateway.current_affordances(task=task, world=self.world),
            history_summary=history_summary,
            completion_progress=completion_progress(task, self.world),
        )

    def _require_task(self) -> ActiveTask:
        if self.active_task is None:
            raise RuntimeError("No active task. Call submit_command first.")
        return self.active_task
