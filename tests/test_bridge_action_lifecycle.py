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


def test_terminal_action_cache_is_fifo_bounded() -> None:
    world = HeadlessGameWorld(
        terminal_action_cache_limit=3,
        request_cache_limit=8,
    )
    for index in range(5):
        action_id = f"bounded.{index}"
        world.request_action(
            action_id=action_id,
            action_name="wait",
            arguments={"duration_ms": 1},
        )
        world.advance(1)

    assert not world.actions.active_records
    assert list(world.actions.terminal_records) == [
        "bounded.2",
        "bounded.3",
        "bounded.4",
    ]
    state = world.gameplay_state()
    assert state["active_actions"] == {}
    assert "terminal_action_cache" not in state


def test_retained_terminal_action_remains_idempotent() -> None:
    world = HeadlessGameWorld(terminal_action_cache_limit=4)
    world.request_action(
        action_id="terminal.duplicate",
        action_name="wait",
        arguments={"duration_ms": 1},
    )
    world.advance(1)
    record = world.actions.get("terminal.duplicate")
    assert record is not None
    version_before = world.world_version
    mutation_before = world.mutation_count

    response = world.request_action(
        action_id="terminal.duplicate",
        action_name="wait",
        arguments={"duration_ms": 1},
        message_id="request.terminal.duplicate.second",
        based_on_world_version=record.based_on_world_version,
    )[-1]

    assert response.message_kind is MessageKind.ACTION_COMPLETED
    assert response.payload["duplicate"] is True
    assert world.world_version == version_before
    assert world.mutation_count == mutation_before


def test_request_cache_is_fifo_bounded() -> None:
    world = HeadlessGameWorld(request_cache_limit=3)
    for index in range(6):
        world.request_action(
            action_id=f"request-cache.{index}",
            action_name="wait",
            arguments={"duration_ms": 1},
            message_id=f"request-cache.message.{index}",
        )
        world.advance(1)
    assert world.request_cache_size == 3


def test_report_history_is_bounded_in_live_state() -> None:
    world = HeadlessGameWorld(report_history_limit=3)
    world.facts.append(
        {
            "fact_id": "fact.bridge.claimed_name.001",
            "subject": "visitor.xiaoman",
            "predicate": "claimed_name",
            "value": "Xiaoman",
            "source": "visitor_statement",
            "certainty": "CLAIMED",
        }
    )
    for index in range(5):
        world.request_action(
            action_id=f"report-history.{index}",
            action_name="report",
            arguments={
                "fact_ids": ["fact.bridge.claimed_name.001"],
                "tone": f"tone-{index}",
            },
        )
        world.advance(600)

    assert len(world.reports) == 3
    assert [item["tone"] for item in world.reports] == ["tone-2", "tone-3", "tone-4"]
    assert len(world.gameplay_state()["reports"]) == 3
