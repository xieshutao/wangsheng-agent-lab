from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .models import Action, Observation, WorldState
from .trace import stable_hash


def compact_observations(
    observations: Iterable[Observation],
    *,
    window: int = 3,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    items = list(observations)
    detailed = tuple(item.to_dict() for item in items[-window:])
    older = items[:-window] if len(items) > window else []
    code_counts = Counter(item.code for item in older)
    failure_counts = Counter(item.code for item in older if not item.success)
    summary = {
        "schema_version": "wangsheng.history_summary.v1",
        "total_prior_results": len(items),
        "detail_window": len(detailed),
        "older_result_count": len(older),
        "older_code_counts": dict(sorted(code_counts.items())),
        "older_failure_counts": dict(sorted(failure_counts.items())),
        "latest_failure": next(
            (
                {
                    "code": item.code,
                    "action": semantic_action_payload(item.action),
                    "message": item.message,
                    "evidence": item.evidence,
                }
                for item in reversed(items)
                if not item.success
            ),
            None,
        ),
    }
    return detailed, summary


def semantic_action_payload(action: Action) -> dict[str, Any]:
    parameters = dict(action.parameters)
    if action.name == "ask_through":
        parameters = {
            "barrier_id": parameters.get("barrier_id"),
            "topic": parameters.get("topic"),
        }
    elif action.name == "report":
        if isinstance(parameters.get("fact_ids"), list):
            parameters = {"fact_ids": sorted(str(item) for item in parameters["fact_ids"])}
        else:
            normalized_facts = []
            for fact in parameters.get("facts", []):
                if not isinstance(fact, dict):
                    continue
                normalized_facts.append(
                    {
                        "subject": fact.get("subject"),
                        "predicate": fact.get("predicate"),
                        "value": fact.get("value"),
                        "certainty": fact.get("certainty"),
                        "source": fact.get("source"),
                    }
                )
            parameters = {
                "facts": sorted(
                    normalized_facts,
                    key=lambda item: (
                        str(item.get("predicate")),
                        str(item.get("value")),
                        str(item.get("source")),
                    ),
                )
            }
    return {
        "name": action.name,
        "target": action.target,
        "parameters": parameters,
    }


def semantic_action_fingerprint(action: Action, world: WorldState) -> str:
    progress = progress_snapshot(world)
    # Positive waiting intentionally advances bounded simulated time. Keep that
    # progress visible so a task designed to wait N ticks is not mistaken for a
    # no-progress loop. Zero-second waits still collapse to the same signature.
    if action.name == "wait" and float(action.parameters.get("seconds", 0) or 0) > 0:
        progress = {**progress, "time_seconds": world.time_seconds}
    return stable_hash(
        {
            "progress": progress,
            "action": semantic_action_payload(action),
        }
    )


def progress_snapshot(world: WorldState) -> dict[str, Any]:
    """State that represents semantic progress, excluding clocks and simulator queues."""

    return {
        "actor_location": world.actor.location,
        "objects": {
            object_id: {
                "state": obj.state,
                "reachable": obj.properties.get("reachable", True),
                "locked": obj.properties.get("locked", False),
            }
            for object_id, obj in sorted(world.objects.items())
        },
        "heard_events": list(world.heard_events),
        "conversation_facts": list(world.conversation_facts),
        "accessible_memories": [item.to_dict() for item in world.accessible_memories()],
        # Reports are outputs, not new evidence. Repeating the same semantic
        # report must not manufacture progress merely by appending another log.
        "emotional_residue": list(world.emotional_residue),
    }
