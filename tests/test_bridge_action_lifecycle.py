from __future__ import annotations

import pytest

from wangsheng.bridge.action_lifecycle import ActionLedger, ActionRecord, ActionStatus
from wangsheng.bridge.errors import BridgeErrorCode, BridgeProtocolError
from wangsheng.bridge.headless_world import HeadlessGameWorld
from wangsheng.bridge.messages import MessageKind


def record(action_id: str = "a1", **overrides: object) -> ActionRecord:
    values = {
        "action_id": action_id,
        "actor_id": "npc.qingyan",
        "action_name": "wait",
        "arguments": {"duration_ms": 1},
        "based_on_world_epoch": "epoch.0001",
        "based_on_world_version": 0,
        "deadline_virtual_time_ms": None,
        "task_generation": 1,
    }
    values.update(overrides)
    return ActionRecord(**values)  # type: ignore[arg-type]


def test_action_lifecycle_reaches_one_terminal_state() -> None:
    ledger = ActionLedger()
    item, created = ledger.register(record())
    assert created
    ledger.transition(item.action_id, ActionStatus.ACCEPTED, now_ms=0)
    ledger.transition(item.action_id, ActionStatus.STARTED, now_ms=0)
    ledger.transition(item.action_id, ActionStatus.COMPLETED, now_ms=1, code="COMPLETED")
    ledger.transition(item.action_id, ActionStatus.FAILED, now_ms=2, code="LATE")
    assert item.status is ActionStatus.COMPLETED
    assert item.terminal_code == "COMPLETED"


def test_duplicate_action_conflict_is_rejected() -> None:
    ledger = ActionLedger()
    ledger.register(record())
    with pytest.raises(BridgeProtocolError) as exc:
        ledger.register(record(arguments={"duration_ms": 2}))
    assert exc.value.code is BridgeErrorCode.DUPLICATE_ACTION_CONFLICT


def test_world_action_completes_asynchronously() -> None:
    world = HeadlessGameWorld()
    responses = world.request_action(
        action_id="move.1",
        action_name="move_to",
        arguments={"target_id": "door.front"},
    )
    assert [item.message_kind for item in responses] == [
        MessageKind.ACTION_ACCEPTED,
        MessageKind.ACTION_STARTED,
    ]
    assert world.entities["npc.qingyan"]["location"] == "anchor.player"
    world.advance(999)
    assert world.actions.records["move.1"].status is ActionStatus.STARTED
    world.advance(1)
    assert world.actions.records["move.1"].status is ActionStatus.COMPLETED
    assert world.entities["npc.qingyan"]["location"] == "anchor.door"


def test_stale_version_rejection_causes_zero_world_mutation() -> None:
    world = HeadlessGameWorld()
    world.apply_world_event("door_locked", {"locked": True})
    before_version = world.world_version
    before_digest = world.state_digest()
    response = world.request_action(
        action_id="stale.1",
        action_name="observe",
        arguments={"target_id": "door.front"},
        based_on_world_version=0,
    )[-1]
    assert response.payload["error_code"] == BridgeErrorCode.STALE_WORLD_VERSION.value
    assert world.world_version == before_version
    assert world.state_digest() == before_digest
    assert "stale.1" not in world.actions.records


def test_cancelled_action_ignores_late_completion() -> None:
    world = HeadlessGameWorld()
    world.request_action(
        action_id="cancel.1",
        action_name="move_to",
        arguments={"target_id": "door.front"},
    )
    world.advance(400)
    world.cancel_task()
    version = world.world_version
    world.simulate_completion_callback("cancel.1")
    assert world.actions.records["cancel.1"].status is ActionStatus.CANCELLED
    assert world.world_version == version
    assert world.entities["npc.qingyan"]["location"] == "anchor.player"
