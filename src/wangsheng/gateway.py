from __future__ import annotations

from dataclasses import dataclass, field

from .models import Action, ActiveTask, Observation, WorldState
from .reason_codes import ReasonCode
from .tools import ToolRegistry


@dataclass(slots=True)
class Gateway:
    registry: ToolRegistry = field(default_factory=ToolRegistry)

    def validate(self, *, action: Action, task: ActiveTask, world: WorldState) -> Observation | None:
        if task.is_terminal:
            code = ReasonCode.TASK_CANCELLED if task.status.value == "cancelled" else ReasonCode.TASK_TERMINAL
            return self._reject(action, code, "The task is no longer active.")

        spec = self.registry.get(action.name)
        if spec is None:
            return self._reject(action, ReasonCode.TOOL_NOT_FOUND, f"Unknown tool '{action.name}'.")
        if action.name not in task.spec.allowed_actions:
            return self._reject(action, ReasonCode.TOOL_NOT_AVAILABLE, f"Tool '{action.name}' is not available for this task.")

        argument_failure = self.registry.validate_action_arguments(action)
        if argument_failure:
            return self._reject(action, argument_failure.code, argument_failure.message)

        targets = [target for target in (action.target, action.parameters.get("barrier_id")) if target]
        for target in targets:
            if not world.target_exists(target):
                return self._reject(action, ReasonCode.TARGET_NOT_FOUND, f"Target '{target}' does not exist.")
            if target not in world.actor.known_targets and target not in {"player", world.actor.character_id}:
                return self._reject(action, ReasonCode.TARGET_NOT_KNOWN, f"Target '{target}' is not known to the actor.")

        if spec.permission not in world.actor.permissions:
            return self._reject(action, ReasonCode.NO_PERMISSION, f"Actor lacks permission '{spec.permission}'.")

        precondition = self._check_preconditions(action, world)
        if precondition:
            return precondition

        if action.name in task.spec.forbidden_actions:
            return self._reject(action, ReasonCode.HARD_CONSTRAINT_VIOLATION, f"Tool '{action.name}' violates the task constraint.")
        if action.name == "open" and action.target == "door.front" and "door.front.must_remain_closed" in task.spec.hard_constraints:
            return self._reject(action, ReasonCode.HARD_CONSTRAINT_VIOLATION, "The front door must remain closed.")
        return None

    def _check_preconditions(self, action: Action, world: WorldState) -> Observation | None:
        if action.name in {"open", "close"}:
            assert action.target is not None
            obj = world.objects[action.target]
            if obj.object_type != "door":
                return self._reject(action, ReasonCode.INVALID_PRECONDITION, "Target is not a door.")
            if action.name == "open":
                if obj.properties.get("locked", False):
                    return self._reject(action, ReasonCode.LOCKED, "The door is locked.")
                if obj.state == "open":
                    return self._reject(action, ReasonCode.INVALID_PRECONDITION, "The door is already open.")
            if action.name == "close" and obj.state != "open":
                return self._reject(action, ReasonCode.INVALID_PRECONDITION, "The door is not open.")
        if action.name == "ask_through":
            barrier_id = action.parameters["barrier_id"]
            barrier = world.objects[barrier_id]
            if barrier.object_type != "door":
                return self._reject(action, ReasonCode.INVALID_PRECONDITION, "The barrier is not supported.")
        return None

    @staticmethod
    def _reject(action: Action, code: ReasonCode | str, message: str) -> Observation:
        value = code.value if isinstance(code, ReasonCode) else code
        return Observation(False, value, message, action, source="gateway")
