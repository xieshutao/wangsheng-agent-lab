from __future__ import annotations

import json

from wangsheng.contracts import MemoryAccess, MemoryEvent
from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.models import Action, ActiveTask, WorldState
from wangsheng.policy import ScriptedPolicy
from wangsheng.prompting import ToolCallingPromptBuilder
from wangsheng.reason_codes import ReasonCode
from wangsheng.scenarios import door_visitor_task, door_visitor_world


def test_model_visible_world_hides_canonical_identity_and_raw_claim() -> None:
    world = door_visitor_world()
    model_view = world.context_snapshot()
    serialized = json.dumps(model_view, ensure_ascii=False, sort_keys=True)

    assert model_view["schema_version"] == "wangsheng.model_visible_world.v1"
    assert "visitor.front_001" in model_view["actor"]["known_targets"]
    assert model_view["entities"]["visitor.front_001"]["identity_status"] == "unknown"
    assert "visitor.xiaoman" not in serialized
    assert "Xiaoman" not in serialized
    assert "visitor_claimed_name" not in model_view
    assert "visitor_responses_remaining" not in model_view

    authoritative = world.snapshot()
    assert authoritative["visitor_id"] == "visitor.xiaoman"
    assert authoritative["visitor_claimed_name"] == "Xiaoman"


def test_model_visible_memory_uses_alias_and_filters_sealed_content() -> None:
    world = door_visitor_world()
    world.memory_events = [
        MemoryEvent(
            "memory.old",
            "visitor.xiaoman",
            "claim",
            "Old claim: Ahe.",
            "reality.v1",
            access=MemoryAccess.SEALED,
            predicate="claimed_name",
            value="Ahe",
        ),
        MemoryEvent(
            "memory.current",
            "visitor.xiaoman",
            "claim",
            "Current claim: Xiaoman.",
            "reality.v2",
            access=MemoryAccess.REWRITTEN,
            predicate="claimed_name",
            value="Xiaoman",
        ),
    ]

    model_view = world.context_snapshot()
    serialized = json.dumps(model_view, ensure_ascii=False, sort_keys=True)

    assert "Ahe" not in serialized
    assert "visitor.xiaoman" not in serialized
    assert model_view["memory_events"][0]["subject"] == "visitor.front_001"
    assert model_view["entities"]["visitor.front_001"]["identity_status"] == "claimed"


def test_world_snapshot_roundtrip_preserves_model_alias_map() -> None:
    world = door_visitor_world()
    restored = WorldState.from_snapshot(world.snapshot())
    assert restored.model_target_aliases == {"visitor.front_001": "visitor.xiaoman"}
    assert restored.snapshot() == world.snapshot()


def test_canonicalize_action_resolves_aliases_in_target_barrier_and_facts() -> None:
    world = door_visitor_world()
    ask = world.canonicalize_action(
        Action(
            "ask_through",
            "visitor.front_001",
            {"barrier_id": "door.front", "topic": "identity"},
            "call-1",
        )
    )
    assert ask.target == "visitor.xiaoman"
    assert ask.parameters["barrier_id"] == "door.front"

    report = world.canonicalize_action(
        Action(
            "report",
            "player",
            {
                "text": "The visitor claims to be Xiaoman.",
                "facts": [
                    {
                        "subject": "visitor.front_001",
                        "predicate": "claimed_name",
                        "value": "Xiaoman",
                        "certainty": "CLAIMED",
                        "source": "visitor_statement",
                    }
                ],
            },
        )
    )
    assert report.parameters["facts"][0]["subject"] == "visitor.xiaoman"


def test_affordances_mark_proximity_actions_blocked_until_move() -> None:
    world = door_visitor_world()
    gateway = Gateway()
    task = ActiveTask(door_visitor_task())

    before = gateway.current_affordances(task=task, world=world)
    assert before["move_to"]["targets"]["door.front"]["executable_now"]
    assert not before["listen_at"]["targets"]["door.front"]["executable_now"]
    assert before["listen_at"]["targets"]["door.front"]["blocked_by"] == ReasonCode.TOO_FAR.value
    assert not before["ask_through"]["targets"]["visitor.front_001"]["executable_now"]
    assert before["open"]["forbidden_by_task"]
    assert before["open"]["blocked_by"] == ReasonCode.HARD_CONSTRAINT_VIOLATION.value

    SimulatedExecutor().execute(
        action=Action("move_to", "door.front", {"acceptance_radius": 80}),
        world=world,
    )
    after = gateway.current_affordances(task=task, world=world)
    assert after["listen_at"]["targets"]["door.front"]["executable_now"]
    assert after["ask_through"]["targets"]["visitor.front_001"]["executable_now"]


def test_gateway_rejects_alias_observation_through_closed_door() -> None:
    world = door_visitor_world()
    gateway = Gateway()
    task = ActiveTask(door_visitor_task())
    requested = Action("observe", "visitor.front_001")
    canonical = gateway.canonicalize_action(action=requested, world=world)
    rejection = gateway.validate(action=canonical, task=task, world=world)

    assert canonical.target == "visitor.xiaoman"
    assert rejection is not None
    assert rejection.code == ReasonCode.INVALID_PRECONDITION.value


def test_engine_executes_model_visible_alias_against_canonical_world() -> None:
    world = door_visitor_world()
    policy = ScriptedPolicy(
        [
            Action("move_to", "door.front", {"acceptance_radius": 80}),
            Action(
                "ask_through",
                "visitor.front_001",
                {"barrier_id": "door.front", "topic": "identity"},
            ),
        ]
    )
    engine = EpisodeEngine(
        world,
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    engine.submit_command(door_visitor_task())
    assert engine.tick().success
    result = engine.tick()
    assert result.success
    assert result.action.target == "visitor.xiaoman"
    assert result.evidence["subject"] == "visitor.xiaoman"


def test_tool_calling_prompt_uses_authorization_affordances_and_aliases() -> None:
    engine = EpisodeEngine(
        door_visitor_world(),
        ScriptedPolicy([]),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(door_visitor_task())
    context = engine.build_context(task)
    messages = ToolCallingPromptBuilder().build_messages(context)
    payload = json.loads(messages[1]["content"])
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert "authorized_actions" in payload
    assert "available_actions" not in payload
    listen_target = payload["current_affordances"]["listen_at"]["targets"][
        "door.front"
    ]
    assert listen_target["blocked_by"] == "TOO_FAR"
    assert "visitor.front_001" in serialized
    assert "visitor.xiaoman" not in serialized
    assert "Xiaoman" not in serialized
