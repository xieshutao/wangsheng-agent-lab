from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import MemoryEvent
from .models import Action, ActiveTask, Observation, WorldState
from .reason_codes import ReasonCode
from .reporting import resolve_fact_ids


@dataclass(slots=True)
class SimulatedExecutor:
    def execute(
        self,
        *,
        action: Action,
        world: WorldState,
        task: ActiveTask | None = None,
    ) -> Observation:
        forced = world.forced_action_results.get(action.name)
        if forced:
            code = forced.pop(0)
            if code != ReasonCode.NONE.value:
                return self._with_failure_guidance(
                    Observation(
                        False,
                        code,
                        f"Forced simulator result for '{action.name}': {code}.",
                        action,
                        source="executor",
                    )
                )
        if action.name == "report":
            observation = self._do_report(action=action, world=world, task=task)
        else:
            handler = getattr(self, f"_do_{action.name}", None)
            if handler is None:
                observation = Observation(
                    False,
                    ReasonCode.EXECUTOR_MISSING.value,
                    f"No handler for '{action.name}'.",
                    action,
                    source="executor",
                )
            else:
                observation = handler(action=action, world=world)
        return observation if observation.success else self._with_failure_guidance(observation)

    def _do_move_to(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        if action.target == "player":
            destination = world.player_location
        elif action.target in world.objects:
            obj = world.objects[action.target]
            if obj.properties.get("reachable", True) is False:
                return Observation(
                    False,
                    ReasonCode.NO_PATH.value,
                    f"No path to '{action.target}'.",
                    action,
                    source="executor",
                )
            destination = obj.location
        else:
            destination = world.actor.location
        previous = world.actor.location
        world.actor.location = destination
        return Observation(
            True,
            ReasonCode.ARRIVED.value,
            f"Arrived at '{action.target}'.",
            action,
            source="executor",
            world_delta={"actor.location": {"from": previous, "to": destination}},
        )

    def _do_observe(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        if action.target in world.objects:
            obj = world.objects[action.target]
            evidence = {
                "target_id": action.target,
                "object_type": obj.object_type,
                "state": obj.state,
                "properties": dict(obj.properties),
            }
        else:
            evidence = {"target_id": action.target, "present": True}
        return Observation(
            True,
            ReasonCode.OBSERVED.value,
            f"Observed '{action.target}'.",
            action,
            source="executor",
            evidence=evidence,
        )

    def _do_listen_at(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        if world.actor.location != obj.location:
            return Observation(
                False,
                ReasonCode.TOO_FAR.value,
                f"Actor is not near '{action.target}'.",
                action,
                source="executor",
            )
        event = "A person is waiting outside the closed front door."
        if event not in world.heard_events:
            world.heard_events.append(event)
        if world.visitor_id:
            fact = {
                "subject": world.visitor_id,
                "predicate": "presence",
                "value": "waiting_outside_closed_front_door",
                "source": "auditory_observation",
                "certainty": "TRUE",
                "verified": True,
            }
            if fact not in world.conversation_facts:
                world.conversation_facts.append(fact)
        return Observation(
            True,
            ReasonCode.HEARD_VISITOR.value,
            event,
            action,
            source="executor",
            evidence={
                "source": "auditory_observation",
                "visitor_present": world.visitor_id is not None,
                "predicate": "presence",
                "value": "waiting_outside_closed_front_door",
            },
        )

    def _do_ask_through(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        barrier_id = action.parameters["barrier_id"]
        barrier = world.objects[barrier_id]
        if world.actor.location != barrier.location:
            return Observation(
                False,
                ReasonCode.TOO_FAR.value,
                f"Actor is not near '{barrier_id}'.",
                action,
                source="executor",
            )
        if action.target != world.visitor_id:
            return Observation(
                False,
                ReasonCode.NO_RESPONSE.value,
                "The requested person did not answer.",
                action,
                source="executor",
            )

        topic = str(action.parameters.get("topic", "identity"))
        if topic == "identity":
            response = (
                world.visitor_responses.pop(0)
                if world.visitor_responses
                else world.visitor_claimed_name
            )
            if response is None:
                return Observation(
                    False,
                    ReasonCode.NO_RESPONSE.value,
                    "No identity response was heard.",
                    action,
                    source="executor",
                )
            fact = {
                "subject": action.target,
                "predicate": "claimed_name",
                "value": response,
                "source": "visitor_statement",
                "certainty": "CLAIMED",
                "verified": False,
            }
            message = f"The visitor claims to be {response}."
            memory_kind = "claim"
        elif topic == "purpose":
            fact = {
                "subject": action.target,
                "predicate": "visit_purpose",
                "value": "speak_with_player",
                "source": "visitor_statement",
                "certainty": "CLAIMED",
                "verified": False,
            }
            message = "The visitor says they are here to speak with the player."
            memory_kind = "claim"
        elif topic == "request":
            fact = {
                "subject": action.target,
                "predicate": "visitor_request",
                "value": "notify_player_of_arrival",
                "source": "visitor_statement",
                "certainty": "CLAIMED",
                "verified": False,
            }
            message = "The visitor asks Qingyan to notify the player of their arrival."
            memory_kind = "claim"
        elif topic == "door_state":
            fact = {
                "subject": barrier_id,
                "predicate": "door_state",
                "value": barrier.state,
                "source": "direct_observation",
                "certainty": "TRUE",
                "verified": True,
            }
            message = f"The front door is {barrier.state}."
            memory_kind = "fact"
        else:
            return Observation(
                False,
                ReasonCode.INVALID_ARGUMENT.value,
                f"Unsupported structured topic '{topic}'.",
                action,
                source="executor",
            )

        if fact not in world.conversation_facts:
            world.conversation_facts.append(fact)
        memory = MemoryEvent(
            memory_id=f"memory.{fact['predicate']}.{len(world.memory_events) + 1:03d}",
            subject=str(fact["subject"]),
            kind=memory_kind,
            content=message,
            source=str(fact["source"]),
            confidence=0.85 if fact["certainty"] == "CLAIMED" else 1.0,
            predicate=str(fact["predicate"]),
            value=str(fact["value"]),
        )
        if not any(
            item.predicate == memory.predicate
            and item.value == memory.value
            and item.source == memory.source
            for item in world.memory_events
        ):
            world.memory_events.append(memory)
        return Observation(
            True,
            ReasonCode.ASK_SUCCEEDED.value,
            message,
            action,
            source="executor",
            evidence={**fact, "topic": topic},
        )

    def _do_open(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        previous = obj.state
        obj.state = "open"
        return Observation(
            True,
            ReasonCode.OPENED.value,
            f"'{action.target}' opened.",
            action,
            source="executor",
            world_delta={f"objects.{action.target}.state": {"from": previous, "to": "open"}},
        )

    def _do_close(self, *, action: Action, world: WorldState) -> Observation:
        assert action.target is not None
        obj = world.objects[action.target]
        previous = obj.state
        obj.state = "closed"
        return Observation(
            True,
            ReasonCode.CLOSED.value,
            f"'{action.target}' closed.",
            action,
            source="executor",
            world_delta={f"objects.{action.target}.state": {"from": previous, "to": "closed"}},
        )

    def _do_report(
        self,
        *,
        action: Action,
        world: WorldState,
        task: ActiveTask | None,
    ) -> Observation:
        assert action.target is not None
        if action.target == "player" and world.actor.location != world.player_location:
            return Observation(
                False,
                ReasonCode.TOO_FAR.value,
                "Actor must return to the player before reporting.",
                action,
                source="executor",
            )

        fact_ids = list(action.parameters.get("fact_ids", []))
        if fact_ids:
            facts, missing = resolve_fact_ids(fact_ids, world=world, task=task)
            if missing:
                return Observation(
                    False,
                    ReasonCode.REPORT_INVALID.value,
                    "Report selected one or more unknown or inaccessible fact_ids.",
                    action,
                    source="executor",
                    evidence={
                        "invalid_fact_ids": missing,
                        "retryable": True,
                        "required_change_before_retry": (
                            "select only IDs currently listed in world.reportable_facts"
                        ),
                    },
                )
        else:
            facts = list(action.parameters.get("facts", []))
            invalid = [fact for fact in facts if not self._fact_is_grounded(fact, world)]
            if invalid:
                return Observation(
                    False,
                    ReasonCode.REPORT_INVALID.value,
                    "Legacy report contains an ungrounded or overconfident fact.",
                    action,
                    source="executor",
                    evidence={
                        "invalid_facts": invalid,
                        "retryable": True,
                        "required_change_before_retry": (
                            "select stable fact_ids from world.reportable_facts"
                        ),
                    },
                )

        report = {
            "target_id": action.target,
            "text": action.parameters["text"],
            "fact_ids": fact_ids,
            "facts": facts,
        }
        world.reports.append(report)
        return Observation(
            True,
            ReasonCode.REPORT_RECORDED.value,
            "Report delivered.",
            action,
            source="executor",
            evidence=report,
        )

    @staticmethod
    def _fact_is_grounded(fact: dict[str, Any], world: WorldState) -> bool:
        predicate = fact.get("predicate")
        value = fact.get("value")
        certainty = fact.get("certainty")
        source = fact.get("source")
        if predicate == "claimed_name":
            if certainty != "CLAIMED":
                return False
            return world.has_accessible_fact(predicate="claimed_name", value=value)
        if predicate == "identity_status" and value == "UNKNOWN":
            return not world.has_accessible_fact(predicate="claimed_name")
        if predicate == "identity_status" and value == "CONFLICTED":
            names = {
                item.value
                for item in world.accessible_memories()
                if item.predicate == "claimed_name" and item.value
            }
            names.update(
                item.get("value")
                for item in world.conversation_facts
                if item.get("predicate") == "claimed_name" and item.get("value")
            )
            return len(names) >= 2 and certainty == "CONFLICTED"
        if predicate == "emotion":
            accessible = any(
                item.kind == "emotion" and item.value == value
                for item in world.accessible_memories()
            )
            return accessible or value in world.emotional_residue
        if predicate == "refusal":
            return certainty == "TRUE" and source == "character_rule"
        return world.has_accessible_fact(predicate=str(predicate), value=str(value))

    def _do_wait(self, *, action: Action, world: WorldState) -> Observation:
        seconds = float(action.parameters["seconds"])
        previous = world.time_seconds
        world.time_seconds += seconds
        return Observation(
            True,
            ReasonCode.WAITED.value,
            f"Waited {seconds:g} seconds.",
            action,
            source="executor",
            world_delta={"time_seconds": {"from": previous, "to": world.time_seconds}},
        )

    @staticmethod
    def _with_failure_guidance(observation: Observation) -> Observation:
        guidance: dict[str, dict[str, Any]] = {
            ReasonCode.NO_PATH.value: {
                "retryable": False,
                "world_changed": False,
                "required_change_before_retry": (
                    "choose another reachable target or wait for a navigation-state change"
                ),
            },
            ReasonCode.TOO_FAR.value: {
                "retryable": True,
                "world_changed": False,
                "required_change_before_retry": "move to the required nearby target first",
            },
            ReasonCode.TIMEOUT.value: {
                "retryable": True,
                "world_changed": False,
                "required_change_before_retry": (
                    "one bounded retry is allowed; change strategy if it times out again"
                ),
            },
            ReasonCode.NO_RESPONSE.value: {
                "retryable": True,
                "world_changed": False,
                "required_change_before_retry": "ask a different structured topic or report no response",
            },
            ReasonCode.REPORT_INVALID.value: {
                "retryable": True,
                "world_changed": False,
                "required_change_before_retry": (
                    "select only current world.reportable_facts IDs"
                ),
            },
        }
        additions = guidance.get(observation.code)
        if not additions:
            return observation
        evidence = dict(observation.evidence)
        for key, value in additions.items():
            evidence.setdefault(key, value)
        return Observation(
            observation.success,
            observation.code,
            observation.message,
            observation.action,
            source=observation.source,
            world_delta=dict(observation.world_delta),
            evidence=evidence,
        )
