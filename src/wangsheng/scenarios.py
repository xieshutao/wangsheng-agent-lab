from __future__ import annotations

from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .models import Action, CharacterState, TaskSpec, WorldObject, WorldState
from .policy import ScriptedPolicy
from .engine import EpisodeEngine
from .tools import ToolRegistry


ALL_TOOLS = frozenset(ToolRegistry().names())


def claimed_fact(name: str, subject: str = "visitor.xiaoman") -> dict[str, str]:
    return {"subject": subject, "predicate": "claimed_name", "value": name, "certainty": "CLAIMED", "source": "visitor_statement"}


def door_visitor_world() -> WorldState:
    return WorldState(
        actor=CharacterState(
            "npc.qingyan",
            "room.front_hall",
            {"door.front", "visitor.xiaoman", "player", "object.paper_crane"},
            {"navigate", "perceive", "communicate", "manipulate", "wait"},
        ),
        player_location="room.front_hall",
        objects={
            "door.front": WorldObject("door.front", "door", "area.front_door", "closed", properties={"locked": False, "reachable": True}),
            "object.paper_crane": WorldObject("object.paper_crane", "item", "room.front_hall", "intact", properties={"reachable": True}),
        },
        visitor_id="visitor.xiaoman",
        visitor_claimed_name="Xiaoman",
        visitor_responses=["Xiaoman"],
        model_target_aliases={"visitor.front_001": "visitor.xiaoman"},
    )


def door_visitor_task(max_steps: int = 12, required_report_fact: str = "Xiaoman") -> TaskSpec:
    return TaskSpec(
        "door_visitor_001",
        "Confirm who is outside the front door, do not open it, return, and report the source-qualified fact.",
        ALL_TOOLS,
        frozenset({"open"}),
        required_report_fact,
        frozenset({"door.front.must_remain_closed"}),
        max_steps,
    )


def reference_door_actions(name: str = "Xiaoman") -> list[Action]:
    return [
        Action("move_to", "door.front", {"acceptance_radius": 80}),
        Action("listen_at", "door.front", {"duration": 2}),
        Action("ask_through", "visitor.xiaoman", {"barrier_id": "door.front", "topic": "identity"}),
        Action("move_to", "player", {"acceptance_radius": 120}),
        Action("report", "player", {"text": f"The visitor claims to be {name}.", "facts": [claimed_fact(name)]}),
    ]


def make_reference_door_engine(max_steps: int = 12) -> EpisodeEngine:
    return EpisodeEngine(door_visitor_world(), ScriptedPolicy(reference_door_actions()), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
