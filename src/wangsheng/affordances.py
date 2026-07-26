from __future__ import annotations

from typing import Any

from .models import ActiveTask, WorldState
from .reason_codes import ReasonCode
from .reporting import completion_progress, required_fact_types
from .tools import ToolRegistry


def build_current_affordances(
    *,
    world: WorldState,
    task: ActiveTask,
    registry: ToolRegistry,
) -> dict[str, Any]:
    """Describe immediate action feasibility without replacing the Gateway.

    The result is advisory model context. The Gateway remains authoritative and
    revalidates every action. Targets are emitted with model-visible aliases so
    hidden canonical IDs never need to enter a prompt.
    """

    result: dict[str, Any] = {}
    for tool_name in sorted(task.spec.allowed_actions):
        spec = registry.get(tool_name)
        if spec is None:
            continue
        entry: dict[str, Any] = {
            "permission": spec.permission,
            "target_required": spec.target_required,
            "forbidden_by_task": tool_name in task.spec.forbidden_actions,
        }
        if spec.permission not in world.actor.permissions:
            entry.update(
                _blocked(
                    ReasonCode.NO_PERMISSION,
                    f"requires permission {spec.permission}",
                )
            )
            result[tool_name] = entry
            continue
        if tool_name in task.spec.forbidden_actions:
            entry.update(
                _blocked(
                    ReasonCode.HARD_CONSTRAINT_VIOLATION,
                    "the active task explicitly forbids this action",
                )
            )
            result[tool_name] = entry
            continue
        handler = globals().get(f"_afford_{tool_name}")
        if handler is None:
            entry.update(_allowed())
        elif tool_name in {"ask_through", "report"}:
            entry.update(handler(world, task))
        else:
            entry.update(handler(world))
        result[tool_name] = entry
    return result


def _afford_move_to(world: WorldState) -> dict[str, Any]:
    targets: dict[str, Any] = {
        "player": _target_allowed("moves to the player's current location")
    }
    for canonical_id, obj in sorted(world.objects.items()):
        if canonical_id not in world.actor.known_targets:
            continue
        visible_id = world.model_target_id(canonical_id)
        if obj.properties.get("reachable", True) is False:
            targets[visible_id] = _target_blocked(
                ReasonCode.NO_PATH,
                "the current navigation graph marks this target unreachable",
            )
        else:
            targets[visible_id] = _target_allowed(f"destination is {obj.location}")
    return _targets_entry(targets)


def _afford_observe(world: WorldState) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for canonical_id, obj in sorted(world.objects.items()):
        if canonical_id in world.actor.known_targets:
            targets[world.model_target_id(canonical_id)] = _target_allowed(
                f"known {obj.object_type} can be inspected"
            )
    for canonical_id in sorted(world.actor.known_targets):
        if canonical_id in world.objects or canonical_id in {
            "player",
            world.actor.character_id,
        }:
            continue
        visible_id = world.model_target_id(canonical_id)
        if canonical_id == world.visitor_id and _front_door_closed(world):
            targets[visible_id] = _target_blocked(
                ReasonCode.INVALID_PRECONDITION,
                "the entity is outside a closed opaque door; use listen_at "
                "or ask_through after moving near the door",
            )
        else:
            targets[visible_id] = _target_allowed("entity is currently observable")
    return _targets_entry(targets)


def _afford_listen_at(world: WorldState) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for canonical_id, obj in sorted(world.objects.items()):
        if canonical_id not in world.actor.known_targets or obj.object_type != "door":
            continue
        visible_id = world.model_target_id(canonical_id)
        if world.actor.location == obj.location:
            targets[visible_id] = _target_allowed("actor is already near the barrier")
        else:
            targets[visible_id] = _target_blocked(
                ReasonCode.TOO_FAR,
                f"requires actor.location={obj.location}; use move_to first",
            )
    return _targets_entry(targets)


def _afford_ask_through(world: WorldState, task: ActiveTask) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    barrier = world.objects.get("door.front")
    if world.visitor_id and world.visitor_id in world.actor.known_targets:
        visible_id = world.model_target_id(world.visitor_id)
        if barrier is None or barrier.object_type != "door":
            targets[visible_id] = _target_blocked(
                ReasonCode.INVALID_PRECONDITION,
                "a supported physical barrier is required",
            )
        elif barrier.state != "closed":
            targets[visible_id] = _target_blocked(
                ReasonCode.INVALID_PRECONDITION,
                "ask_through requires the barrier to remain closed",
            )
        elif world.actor.location != barrier.location:
            targets[visible_id] = _target_blocked(
                ReasonCode.TOO_FAR,
                f"requires actor.location={barrier.location}; use move_to(door.front) first",
            )
        else:
            topic_evidence = {
                "identity": ["claimed_name"],
                "purpose": ["visit_purpose"],
                "request": ["visitor_request"],
                "door_state": ["door_state"],
            }
            required = set(required_fact_types(task))
            recommended_topics = sorted(
                topic
                for topic, produces in topic_evidence.items()
                if required.intersection(produces)
            )
            targets[visible_id] = {
                **_target_allowed("actor is near the closed barrier"),
                "required_arguments": {"barrier_id": "door.front"},
                "topic_evidence": topic_evidence,
                "recommended_topics": recommended_topics,
            }
    return _targets_entry(targets)


def _afford_open(world: WorldState) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for canonical_id, obj in sorted(world.objects.items()):
        if canonical_id not in world.actor.known_targets or obj.object_type != "door":
            continue
        visible_id = world.model_target_id(canonical_id)
        if obj.properties.get("locked", False):
            targets[visible_id] = _target_blocked(ReasonCode.LOCKED, "door is locked")
        elif obj.state == "open":
            targets[visible_id] = _target_blocked(
                ReasonCode.INVALID_PRECONDITION,
                "door is already open",
            )
        elif world.actor.location != obj.location:
            targets[visible_id] = _target_blocked(
                ReasonCode.TOO_FAR,
                f"requires actor.location={obj.location}",
            )
        else:
            targets[visible_id] = _target_allowed("door is closed, unlocked and nearby")
    return _targets_entry(targets)


def _afford_close(world: WorldState) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for canonical_id, obj in sorted(world.objects.items()):
        if canonical_id not in world.actor.known_targets or obj.object_type != "door":
            continue
        visible_id = world.model_target_id(canonical_id)
        if obj.state != "open":
            targets[visible_id] = _target_blocked(
                ReasonCode.INVALID_PRECONDITION,
                "door is not open",
            )
        elif world.actor.location != obj.location:
            targets[visible_id] = _target_blocked(
                ReasonCode.TOO_FAR,
                f"requires actor.location={obj.location}",
            )
        else:
            targets[visible_id] = _target_allowed("open door is nearby")
    return _targets_entry(targets)


def _afford_report(world: WorldState, task: ActiveTask) -> dict[str, Any]:
    progress = completion_progress(task, world)
    accepted = list(progress.get("accepted_fact_ids", []))
    if not accepted:
        missing = list(progress.get("missing_fact_types", []))
        targets = {
            "player": {
                "executable_now": False,
                "blocked_by": "MISSING_TASK_FACT",
                "requires": (
                    f"obtain a reportable fact for {missing}" if missing
                    else "obtain a matching reportable fact"
                ),
                "accepted_fact_ids": [],
            }
        }
    elif world.actor.location == world.player_location:
        targets = {
            "player": {
                **_target_allowed("actor is near the player and a completing fact is available"),
                "accepted_fact_ids": accepted,
            }
        }
    else:
        targets = {
            "player": {
                **_target_blocked(
                    ReasonCode.TOO_FAR,
                    f"requires actor.location={world.player_location}; use move_to(player) first",
                ),
                "accepted_fact_ids": accepted,
            }
        }
    return _targets_entry(targets)


def _afford_wait(world: WorldState) -> dict[str, Any]:
    del world
    return _allowed("bounded waiting is executable now")


def _front_door_closed(world: WorldState) -> bool:
    door = world.objects.get("door.front")
    return bool(door and door.state == "closed")


def _targets_entry(targets: dict[str, Any]) -> dict[str, Any]:
    executable = any(item.get("executable_now") for item in targets.values())
    return {"executable_now": executable, "targets": targets}


def _allowed(note: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"executable_now": True, "blocked_by": None}
    if note:
        payload["note"] = note
    return payload


def _blocked(code: ReasonCode, requires: str) -> dict[str, Any]:
    return {
        "executable_now": False,
        "blocked_by": code.value,
        "requires": requires,
    }


def _target_allowed(note: str) -> dict[str, Any]:
    return {"executable_now": True, "blocked_by": None, "note": note}


def _target_blocked(code: ReasonCode, requires: str) -> dict[str, Any]:
    return {
        "executable_now": False,
        "blocked_by": code.value,
        "requires": requires,
    }
