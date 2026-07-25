from __future__ import annotations
from dataclasses import dataclass
from .models import Action, Observation, WorldState

@dataclass(slots=True)
class SimulatedExecutor:
    def execute(self, *, action: Action, world: WorldState) -> Observation:
        handler = getattr(self, f"_do_{action.name}", None)
        if handler is None:
            return Observation(False, "executor_missing", f"No handler for '{action.name}'.", action)
        return handler(action=action, world=world)
    def _do_move_to(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        if action.target == "player": destination = world.player_location
        elif action.target in world.objects: destination = world.objects[action.target].location
        else: destination = world.actor.location
        previous = world.actor.location
        world.actor.location = destination
        return Observation(True, "arrived", f"Arrived at '{action.target}'.", action,
                           {"actor.location": {"from": previous, "to": destination}})
    def _do_listen_at(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        if world.actor.location != obj.location:
            return Observation(False, "out_of_range", f"Not near '{action.target}'.", action)
        if action.target == "front_door" and world.visitor_id:
            event = "A person is waiting outside the closed front door."
            if event not in world.heard_events: world.heard_events.append(event)
            return Observation(True, "heard_visitor", event, action,
                               evidence={"source": "auditory", "visitor_present": True})
        return Observation(True, "heard_nothing", "No relevant sound was heard.", action)
    def _do_talk_to(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        if action.target != world.visitor_id:
            return Observation(False, "not_conversable", f"Cannot talk to '{action.target}'.", action)
        if world.actor.location != world.objects["front_door"].location:
            return Observation(False, "out_of_range", "Must be at the front door.", action)
        claim = {"subject": world.visitor_id, "predicate": "claimed_name",
                 "value": world.visitor_claimed_name, "source": "visitor_statement",
                 "verified": False}
        if claim not in world.conversation_facts: world.conversation_facts.append(claim)
        return Observation(True, "visitor_identified_by_claim",
                           f"The visitor says: 'My name is {world.visitor_claimed_name}.'",
                           action, evidence=claim)
    def _do_return_to(self, *, action: Action, world: WorldState) -> Observation:
        previous = world.actor.location
        world.actor.location = world.player_location
        return Observation(True, "returned_to_player", "Returned to the player.", action,
                           {"actor.location": {"from": previous, "to": world.player_location}})
    def _do_report(self, *, action: Action, world: WorldState) -> Observation:
        text = action.parameters.get("text")
        if not isinstance(text, str) or not text.strip():
            return Observation(False, "report_text_required", "Non-empty report required.", action)
        world.reports.append(text.strip())
        return Observation(True, "report_recorded", "Report delivered.", action,
                           evidence={"report": text.strip()})
    def _do_inspect(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        if world.actor.location != obj.location:
            return Observation(False, "out_of_range", f"Not near '{action.target}'.", action)
        return Observation(True, "inspected", f"'{action.target}' is '{obj.state}'.", action,
                           evidence={"target": action.target, "state": obj.state})
    def _do_wait(self, *, action: Action, world: WorldState) -> Observation:
        return Observation(True, "waited", "Waited for one tick.", action)
    def _do_open(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        previous = obj.state
        obj.state = "open"
        return Observation(True, "opened", f"'{action.target}' was opened.", action,
                           {f"objects.{action.target}.state": {"from": previous, "to": "open"}})
