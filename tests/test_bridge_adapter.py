from __future__ import annotations

from wangsheng.bridge.adapter import HeadlessNpcAdapter
from wangsheng.bridge.headless_world import HeadlessGameWorld
from wangsheng.bridge.messages import MessageKind
from wangsheng.models import Action, ActiveTask
from wangsheng.scenarios import door_visitor_task


def test_adapter_projection_does_not_share_mutable_world_objects() -> None:
    bridge = HeadlessGameWorld()
    adapter = HeadlessNpcAdapter(bridge)
    projected = adapter.project_core_world()
    projected.objects["door.front"].properties["locked"] = True
    projected.actor.location = "mutated"
    assert bridge.door["locked"] is False
    assert bridge.entities["npc.qingyan"]["location"] == "anchor.player"


def test_adapter_preserves_existing_gateway_validation() -> None:
    bridge = HeadlessGameWorld()
    adapter = HeadlessNpcAdapter(bridge)
    task = ActiveTask(door_visitor_task())
    message, rejection = adapter.validated_action_request(
        action=Action("ask_through", "visitor.front_001", {"barrier_id": "door.front", "topic": "identity"}, "a.ask"),
        task=task,
        message_id="msg.ask",
        tick_id="tick.1",
    )
    assert message is None
    assert rejection is not None
    assert rejection.code == "TOO_FAR"


def test_adapter_converts_validated_action_to_bridge_message() -> None:
    bridge = HeadlessGameWorld()
    adapter = HeadlessNpcAdapter(bridge)
    task = ActiveTask(door_visitor_task())
    message, rejection = adapter.validated_action_request(
        action=Action("move_to", "door.front", {"acceptance_radius": 80}, "a.move"),
        task=task,
        message_id="msg.move",
        tick_id="tick.1",
    )
    assert rejection is None
    assert message is not None
    assert message.message_kind is MessageKind.ACTION_REQUESTED
    assert message.payload["arguments"]["target_id"] == "door.front"
