from __future__ import annotations

from dataclasses import dataclass

from .models import Action, Observation, WorldState
from .reason_codes import ReasonCode


@dataclass(slots=True)
class SimulatedExecutor:
    def execute(self, *, action: Action, world: WorldState) -> Observation:
        handler = getattr(self, f"_do_{action.name}", None)
        if handler is None:
            return Observation(False, ReasonCode.EXECUTOR_MISSING.value, f"No handler for '{action.name}'.", action, source="executor")
        return handler(action=action, world=world)

    def _do_move_to(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        if action.target == "player":
            destination = world.player_location
        elif action.target in world.objects:
            obj = world.objects[action.target]
            if obj.properties.get("reachable", True) is False:
                return Observation(False, ReasonCode.NO_PATH.value, f"No path to '{action.target}'.", action, source="executor")
            destination = obj.location
        else:
            destination = world.actor.location
        previous = world.actor.location
        world.actor.location = destination
        return Observation(True, ReasonCode.ARRIVED.value, f"Arrived at '{action.target}'.", action, source="executor", world_delta={"actor.location": {"from": previous, "to": destination}})

    def _do_observe(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        if action.target in world.objects:
            obj = world.objects[action.target]
            evidence = {"target_id": action.target, "object_type": obj.object_type, "state": obj.state, "properties": dict(obj.properties)}
        else:
            evidence = {"target_id": action.target, "present": True}
        return Observation(True, ReasonCode.OBSERVED.value, f"Observed '{action.target}'.", action, source="executor", evidence=evidence)

    def _do_listen_at(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        if world.actor.location != obj.location:
            return Observation(False, ReasonCode.TOO_FAR.value, f"Actor is not near '{action.target}'.", action, source="executor")
        event = "A person is waiting outside the closed front door."
        if event not in world.heard_events:
            world.heard_events.append(event)
        return Observation(True, ReasonCode.HEARD_VISITOR.value, event, action, source="executor", evidence={"source": "auditory", "visitor_present": world.visitor_id is not None})

    def _do_ask_through(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        barrier_id = action.parameters["barrier_id"]
        barrier = world.objects[barrier_id]
        if world.actor.location != barrier.location:
            return Observation(False, ReasonCode.TOO_FAR.value, f"Actor is not near '{barrier_id}'.", action, source="executor")
        if action.target != world.visitor_id:
            return Observation(False, ReasonCode.NO_RESPONSE.value, "The requested person did not answer.", action, source="executor")
        response = world.visitor_responses.pop(0) if world.visitor_responses else world.visitor_claimed_name
        if response is None:
            return Observation(False, ReasonCode.NO_RESPONSE.value, "No response was heard.", action, source="executor")
        claim = {"subject": action.target, "predicate": "claimed_name", "value": response, "source": "visitor_statement", "certainty": "CLAIMED", "verified": False}
        if claim not in world.conversation_facts:
            world.conversation_facts.append(claim)
        return Observation(True, ReasonCode.ASK_SUCCEEDED.value, f"The visitor claims to be {response}.", action, source="executor", evidence=claim)

    def _do_open(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        previous = obj.state
        obj.state = "open"
        return Observation(True, ReasonCode.OPENED.value, f"'{action.target}' opened.", action, source="executor", world_delta={f"objects.{action.target}.state": {"from": previous, "to": "open"}})

    def _do_close(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        previous = obj.state
        obj.state = "closed"
        return Observation(True, ReasonCode.CLOSED.value, f"'{action.target}' closed.", action, source="executor", world_delta={f"objects.{action.target}.state": {"from": previous, "to": "closed"}})

    def _do_report(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        if action.target == "player" and world.actor.location != world.player_location:
            return Observation(False, ReasonCode.TOO_FAR.value, "Actor must return to the player before reporting.", action, source="executor")
        report = {"target_id": action.target, "text": action.parameters["text"], "facts": list(action.parameters["facts"])}
        world.reports.append(report)
        return Observation(True, ReasonCode.REPORT_RECORDED.value, "Report delivered.", action, source="executor", evidence=report)

    def _do_wait(self, *, action: Action, world: WorldState) -> Observation:
        seconds = float(action.parameters["seconds"])
        previous = world.time_seconds
        world.time_seconds += seconds
        return Observation(True, ReasonCode.WAITED.value, f"Waited {seconds:g} seconds.", action, source="executor", world_delta={"time_seconds": {"from": previous, "to": world.time_seconds}})
