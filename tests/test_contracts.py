from __future__ import annotations

from wangsheng.contracts import (
    ActionRequest,
    ActionResult,
    Intent,
    IntentKind,
    MemoryAccess,
    MemoryEvent,
)
from wangsheng.models import Action, Observation, WorldState
from wangsheng.scenarios import door_visitor_world


def test_intent_contract_is_versioned():
    payload = Intent("intent.test", IntentKind.TASK, "Check the door.").to_dict()
    assert payload["schema_version"] == "wangsheng.intent.v1"
    assert payload["kind"] == "task"


def test_action_request_maps_existing_action_without_changing_domain_model():
    request = ActionRequest.from_action(Action("move_to", "door.front", {"acceptance_radius": 80}, "a1"))
    assert request.to_dict()["target_id"] == "door.front"
    assert request.to_dict()["arguments"]["acceptance_radius"] == 80


def test_action_result_maps_observation():
    result = ActionResult.from_observation(Observation(False, "NO_PATH", "blocked", Action("move_to", "door.front", action_id="a1"), source="executor"))
    payload = result.to_dict()
    assert payload["status"] == "failure"
    assert payload["reason_code"] == "NO_PATH"


def test_forgotten_and_sealed_memories_are_not_context_accessible():
    for access in (MemoryAccess.FORGOTTEN, MemoryAccess.SEALED, MemoryAccess.SUPPRESSED):
        memory = MemoryEvent("m", "visitor", "fact", "secret", "test", access=access)
        assert not memory.is_context_accessible


def test_clear_fuzzy_and_rewritten_memories_are_context_accessible():
    for access in (MemoryAccess.CLEAR, MemoryAccess.FUZZY, MemoryAccess.REWRITTEN):
        memory = MemoryEvent("m", "visitor", "fact", "visible", "test", access=access)
        assert memory.is_context_accessible


def test_world_context_snapshot_filters_forgotten_content():
    world = door_visitor_world()
    world.memory_events = [
        MemoryEvent("old", "visitor.xiaoman", "fact", "Ahe", "old", access=MemoryAccess.FORGOTTEN, predicate="claimed_name", value="Ahe"),
        MemoryEvent("new", "visitor.xiaoman", "fact", "Xiaoman", "new", access=MemoryAccess.REWRITTEN, predicate="claimed_name", value="Xiaoman"),
    ]
    context = world.context_snapshot()
    assert "Ahe" not in str(context)
    assert "Xiaoman" in str(context)


def test_world_snapshot_roundtrip_preserves_authoritative_state():
    world = door_visitor_world()
    world.emotional_residue.append("uneasy")
    restored = WorldState.from_snapshot(world.snapshot())
    assert restored.snapshot() == world.snapshot()
