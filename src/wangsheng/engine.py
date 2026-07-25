from __future__ import annotations

from dataclasses import dataclass

from .errors import PolicyOutputError, ProviderError
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .models import (
    Action,
    ActiveTask,
    Observation,
    PolicyContext,
    TaskSpec,
    TaskStatus,
    WorldState,
)
from .policy import Policy


@dataclass(slots=True)
class EpisodeEngine:
    world: WorldState
    policy: Policy
    gateway: Gateway
    executor: SimulatedExecutor
    evaluator: DoorVisitorEvaluator
    active_task: ActiveTask | None = None

    def submit_command(self, spec: TaskSpec) -> ActiveTask:
        if self.active_task is not None and not self.active_task.is_terminal:
            raise RuntimeError("An active task already exists.")
        self.active_task = ActiveTask(spec=spec)
        return self.active_task

    def cancel_task(self, reason: str = "cancelled_by_player") -> ActiveTask:
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
                "task_terminal",
                "No tick after terminal task.",
                Action("wait"),
            )

        context = self._build_context(task)
        try:
            action = self.policy.next_action(context)
        except PolicyOutputError as exc:
            observation = Observation(
                success=False,
                code=exc.code,
                message=str(exc),
                action=Action(
                    name="__invalid_model_output__",
                    parameters={"raw_output": exc.raw_output},
                ),
            )
        except ProviderError as exc:
            observation = Observation(
                success=False,
                code=exc.code,
                message=str(exc),
                action=Action(name="__provider_error__"),
            )
        else:
            rejection = self.gateway.validate(action=action, task=task, world=self.world)
            observation = (
                rejection
                if rejection is not None
                else self.executor.execute(action=action, world=self.world)
            )

        task.step_count += 1
        task.observations.append(observation)
        self.evaluator.update(task=task, world=self.world, observation=observation)
        return observation

    def run_until_terminal(self) -> ActiveTask:
        task = self._require_task()
        while not task.is_terminal:
            self.tick()
        return task

    def _build_context(self, task: ActiveTask) -> PolicyContext:
        return PolicyContext(
            task.spec.command,
            task.spec.task_id,
            task.step_count,
            tuple(sorted(task.spec.allowed_actions)),
            tuple(sorted(task.spec.forbidden_actions)),
            self.world.snapshot(),
            tuple(observation.to_dict() for observation in task.observations),
        )

    def _require_task(self) -> ActiveTask:
        if self.active_task is None:
            raise RuntimeError("No active task. Call submit_command first.")
        return self.active_task
