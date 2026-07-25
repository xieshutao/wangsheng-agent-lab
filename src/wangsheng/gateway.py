from __future__ import annotations
from dataclasses import dataclass
from .models import Action, ActiveTask, Observation, WorldState

@dataclass(slots=True)
class Gateway:
    actions_requiring_target: frozenset[str] = frozenset({"move_to", "listen_at", "talk_to", "inspect", "open"})
    def validate(self, *, action: Action, task: ActiveTask, world: WorldState) -> Observation | None:
        if task.is_terminal:
            return self._reject(action, "task_terminal", "The task is already terminal.")
        if not action.name or not isinstance(action.name, str):
            return self._reject(action, "invalid_action", "Action name must be non-empty.")
        if action.name in task.spec.forbidden_actions:
            return self._reject(action, "action_forbidden", f"Action '{action.name}' is forbidden.")
        if action.name not in task.spec.allowed_actions:
            return self._reject(action, "action_unavailable", f"Action '{action.name}' is unavailable.")
        if action.name in self.actions_requiring_target and not action.target:
            return self._reject(action, "target_required", f"Action '{action.name}' requires a target.")
        if action.target and not world.target_exists(action.target):
            return self._reject(action, "unknown_target", f"Target '{action.target}' does not exist.")
        if action.target and action.target not in world.actor.known_targets and action.target not in {"player", world.actor.character_id}:
            return self._reject(action, "target_not_known", f"Target '{action.target}' is not known to the actor.")
        return None
    @staticmethod
    def _reject(action: Action, code: str, message: str) -> Observation:
        return Observation(False, code, message, action)
