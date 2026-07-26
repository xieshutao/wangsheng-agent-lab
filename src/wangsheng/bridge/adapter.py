from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from wangsheng.gateway import Gateway
from wangsheng.models import Action, ActiveTask, Observation, WorldState
from wangsheng.reporting import resolve_fact_ids
from wangsheng.reason_codes import ReasonCode
from wangsheng.scenarios import door_visitor_world

from .errors import BridgeErrorCode
from .headless_world import HeadlessGameWorld
from .messages import BridgeMessage, MessageKind


@dataclass(slots=True)
class HeadlessNpcAdapter:
    bridge_world: HeadlessGameWorld
    gateway: Gateway = field(default_factory=Gateway)

    def project_core_world(self) -> WorldState:
        """Create a detached core-world projection from authoritative bridge state."""
        core = door_visitor_world()
        npc = self.bridge_world.entities["npc.qingyan"]
        player = self.bridge_world.entities["player"]
        visitor = self.bridge_world.entities["visitor.xiaoman"]
        bridge_to_core_location = {
            "anchor.player": "room.front_hall",
            "anchor.counter": "room.front_hall",
            "anchor.door": "area.front_door",
            "anchor.outside_door": "area.outside_front_door",
        }
        core.actor.location = bridge_to_core_location.get(npc["location"], npc["location"])
        core.player_location = bridge_to_core_location.get(
            player["location"], player["location"]
        )
        door = core.objects["door.front"]
        door.state = "open" if self.bridge_world.door["open"] else "closed"
        door.properties["locked"] = self.bridge_world.door["locked"]
        door.properties["reachable"] = self.bridge_world.door["reachable"]
        core.visitor_id = "visitor.xiaoman" if visitor["present"] else None
        core.conversation_facts = deepcopy(self.bridge_world.facts)
        core.reports = deepcopy(self.bridge_world.reports)
        core.heard_events = list(self.bridge_world.heard_events)
        core.time_seconds = self.bridge_world.virtual_time_ms / 1000.0
        return core

    def validated_action_request(
        self,
        *,
        action: Action,
        task: ActiveTask,
        message_id: str,
        tick_id: str,
    ) -> tuple[BridgeMessage | None, Observation | None]:
        core_world = self.project_core_world()
        canonical = self.gateway.canonicalize_action(action=action, world=core_world)
        rejection = self.gateway.validate(action=canonical, task=task, world=core_world)
        if rejection is not None:
            return None, rejection
        if canonical.name == "report":
            fact_ids = list(canonical.parameters.get("fact_ids", []))
            _, missing = resolve_fact_ids(fact_ids, world=core_world, task=task)
            if missing:
                return None, Observation(
                    False,
                    ReasonCode.REPORT_INVALID.value,
                    "Report selected unknown or inaccessible fact_ids.",
                    canonical,
                    source="gateway",
                    evidence={"invalid_fact_ids": missing},
                )
        arguments = self._bridge_arguments(canonical)
        message = self.bridge_world.make_message(
            MessageKind.ACTION_REQUESTED,
            message_id=message_id,
            action_id=canonical.action_id or f"{task.spec.task_id}.bridge",
            task_id=task.spec.task_id,
            tick_id=tick_id,
            payload={
                "actor_id": "npc.qingyan",
                "action_name": canonical.name,
                "arguments": arguments,
                "based_on_world_epoch": self.bridge_world.world_epoch,
                "based_on_world_version": self.bridge_world.world_version,
                "deadline_virtual_time_ms": self.bridge_world.virtual_time_ms + 5000,
                "task_generation": self.bridge_world.task_generation,
            },
        )
        return message, None

    @staticmethod
    def _bridge_arguments(action: Action) -> dict[str, Any]:
        parameters = dict(action.parameters)
        if action.target is not None:
            parameters.setdefault("target_id", action.target)
        if action.name == "wait" and "seconds" in parameters:
            parameters["duration_ms"] = int(float(parameters.pop("seconds")) * 1000)
        return parameters

    @staticmethod
    def observation_from_terminal(
        message: BridgeMessage,
        action: Action,
        *,
        world: WorldState | None = None,
        task: ActiveTask | None = None,
    ) -> Observation:
        if message.message_kind is MessageKind.ACTION_COMPLETED:
            evidence = dict(message.payload.get("evidence", {}))
            if action.name == "report" and world is not None:
                fact_ids = list(action.parameters.get("fact_ids", []))
                facts, missing = resolve_fact_ids(fact_ids, world=world, task=task)
                evidence = {
                    **evidence,
                    "fact_ids": fact_ids,
                    "facts": facts,
                    "invalid_fact_ids": missing,
                    "rendered_by": "deterministic_fact_renderer",
                }
            return Observation(
                True,
                "BRIDGE_ACTION_COMPLETED",
                "Headless game action completed.",
                action,
                source="headless_bridge",
                world_delta=dict(message.payload.get("world_effect", {})),
                evidence=evidence,
            )
        code = str(message.payload.get("error_code", BridgeErrorCode.INTERNAL_BRIDGE_ERROR.value))
        reason_map = {
            BridgeErrorCode.NO_PATH.value: ReasonCode.NO_PATH.value,
            BridgeErrorCode.LOCKED.value: ReasonCode.LOCKED.value,
            BridgeErrorCode.TARGET_GONE.value: ReasonCode.TARGET_NOT_FOUND.value,
            BridgeErrorCode.ACTION_TIMEOUT.value: ReasonCode.TIMEOUT.value,
            BridgeErrorCode.CANCELLED_BY_PLAYER.value: ReasonCode.TASK_CANCELLED.value,
        }
        return Observation(
            False,
            reason_map.get(code, code),
            str(message.payload.get("message", "Headless game action failed.")),
            action,
            source="headless_bridge",
            evidence={"bridge_error_code": code},
        )
