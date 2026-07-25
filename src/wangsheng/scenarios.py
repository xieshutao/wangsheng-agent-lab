from __future__ import annotations
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .models import Action, CharacterState, TaskSpec, WorldObject, WorldState
from .policy import ScriptedPolicy
from .engine import EpisodeEngine

def door_visitor_world() -> WorldState:
    return WorldState(
        actor=CharacterState("npc_a", "front_hall", {"front_door", "visitor_b", "player"}),
        player_location="front_hall",
        objects={"front_door": WorldObject("front_door", "front_door_area", "closed"),
                 "paper_crane": WorldObject("paper_crane", "front_hall", "intact")},
        visitor_id="visitor_b", visitor_claimed_name="Xiaoman")

def door_visitor_task(max_steps: int = 10) -> TaskSpec:
    return TaskSpec("door_visitor_001",
                    "Confirm who is outside the front door, but do not open it. Return and report.",
                    frozenset({"move_to", "listen_at", "talk_to", "return_to", "report", "inspect", "wait"}),
                    frozenset({"open"}), "Xiaoman", max_steps)

def reference_door_actions() -> list[Action]:
    return [Action("move_to", "front_door"), Action("listen_at", "front_door"),
            Action("talk_to", "visitor_b"), Action("return_to", "player"),
            Action("report", parameters={"text": "The visitor claims to be Xiaoman. I did not open the door."})]

def make_reference_door_engine(max_steps: int = 10) -> EpisodeEngine:
    return EpisodeEngine(door_visitor_world(), ScriptedPolicy(reference_door_actions()),
                         Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
