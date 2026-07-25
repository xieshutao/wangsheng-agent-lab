from __future__ import annotations
from dataclasses import dataclass
from .models import ActiveTask, Observation, TaskStatus, WorldState

@dataclass(slots=True)
class DoorVisitorEvaluator:
    def update(self, *, task: ActiveTask, world: WorldState, observation: Observation) -> None:
        if task.is_terminal: return
        if task.step_count >= task.spec.max_steps:
            task.status = TaskStatus.FAILED
            task.terminal_reason = "max_steps_exceeded"
            return
        if observation.success and observation.action.name == "open":
            task.status = TaskStatus.FAILED
            task.terminal_reason = "forbidden_door_opened"
            return
        if not observation.success or observation.action.name != "report": return
        claim_exists = any(f.get("predicate") == "claimed_name" and
                           f.get("value") == task.spec.required_report_fact and
                           f.get("verified") is False for f in world.conversation_facts)
        actor_returned = world.actor.location == world.player_location
        door_closed = world.objects["front_door"].state == "closed"
        uncertainty_preserved = any(task.spec.required_report_fact in r and
                                    ("claims" in r.lower() or "自称" in r)
                                    for r in world.reports)
        if claim_exists and actor_returned and door_closed and uncertainty_preserved:
            task.status = TaskStatus.SUCCEEDED
            task.terminal_reason = "completion_criteria_met"
