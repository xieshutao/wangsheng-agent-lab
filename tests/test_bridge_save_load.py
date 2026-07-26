from __future__ import annotations

import pytest

from wangsheng.bridge.action_lifecycle import ActionStatus
from wangsheng.bridge.errors import BridgeErrorCode, BridgeProtocolError
from wangsheng.bridge.headless_world import HeadlessGameWorld
from wangsheng.bridge.savegame import SaveGame


def test_idle_save_load_preserves_digest_and_changes_epoch() -> None:
    world = HeadlessGameWorld()
    old_epoch = world.world_epoch
    save = world.export_save()
    world.apply_world_event("door_locked", {"locked": True})
    world.load_save(save)
    assert world.world_epoch != old_epoch
    assert world.state_digest() == save.gameplay_digest
    assert not world.door["locked"]


def test_active_action_save_load_preserves_remaining_duration() -> None:
    world = HeadlessGameWorld()
    world.request_action(
        action_id="active.save",
        action_name="move_to",
        arguments={"target_id": "door.front"},
    )
    world.advance(400)
    save = world.export_save()
    world.load_save(save)
    record = world.actions.records["active.save"]
    assert record.to_dict(now_ms=world.virtual_time_ms)["remaining_duration_ms"] == 600
    world.advance(600)
    assert record.status is ActionStatus.COMPLETED
    assert world.entities["npc.qingyan"]["location"] == "anchor.door"


def test_corrupted_save_leaves_active_world_unchanged() -> None:
    world = HeadlessGameWorld()
    before = world.state_digest()
    payload = world.export_save().to_dict()
    payload["gameplay_state"]["door"]["locked"] = True
    with pytest.raises(BridgeProtocolError) as exc:
        world.load_save(payload)
    assert exc.value.code is BridgeErrorCode.SAVE_CORRUPTED
    assert world.state_digest() == before


def test_save_json_round_trip() -> None:
    world = HeadlessGameWorld()
    save = world.export_save()
    assert SaveGame.from_json(save.to_json()) == save


def test_save_load_starts_a_fresh_epoch_local_terminal_cache() -> None:
    world = HeadlessGameWorld(terminal_action_cache_limit=3)
    for index in range(5):
        world.request_action(
            action_id=f"save-cache.{index}",
            action_name="wait",
            arguments={"duration_ms": 1},
        )
        world.advance(1)

    old_epoch = world.world_epoch
    save = world.export_save()
    assert len(world.actions.terminal_records) == 3
    world.load_save(save)

    assert world.world_epoch != old_epoch
    assert world.actions.terminal_cache_limit == 3
    assert not world.actions.terminal_records
    assert not world.actions.active_records
    assert world.state_digest() == save.gameplay_digest
