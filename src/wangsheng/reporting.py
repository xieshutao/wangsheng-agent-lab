from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Iterable

from .models import ActiveTask, TaskSpec, WorldState


def _certainty_for_fact(fact: dict[str, Any]) -> str:
    certainty = fact.get("certainty")
    if isinstance(certainty, str) and certainty:
        return certainty
    if fact.get("predicate") == "claimed_name" or fact.get("kind") == "claim":
        return "CLAIMED"
    return "TRUE"


def _stable_fact_id(fact: dict[str, Any], *, prefix: str = "fact") -> str:
    material = {
        "subject": fact.get("subject"),
        "predicate": fact.get("predicate"),
        "value": fact.get("value"),
        "certainty": fact.get("certainty"),
        "source": fact.get("source"),
    }
    digest = sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    predicate = str(fact.get("predicate") or "fact").replace("_", "-")
    return f"{prefix}.{predicate}.{digest}"


def _canonical_fact(
    *,
    subject: str,
    predicate: str,
    value: str,
    certainty: str,
    source: str,
    fact_id: str | None = None,
    derived: bool = False,
) -> dict[str, Any]:
    fact = {
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "certainty": certainty,
        "source": source,
        "derived": derived,
    }
    fact["fact_id"] = fact_id or _stable_fact_id(fact)
    return fact


def derive_reportable_facts(
    world: WorldState,
    task: ActiveTask | TaskSpec | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return the deterministic catalog of facts the model may report.

    The catalog is the semantic boundary between model language and world truth.
    Models select stable ``fact_id`` values instead of constructing predicates,
    certainty labels and sources themselves.
    """

    task_spec = task.spec if isinstance(task, ActiveTask) else task
    candidates: list[dict[str, Any]] = []

    for item in world.conversation_facts:
        predicate = item.get("predicate")
        value = item.get("value")
        subject = item.get("subject")
        source = item.get("source")
        if not all(isinstance(part, str) and part for part in (predicate, value, subject, source)):
            continue
        candidates.append(
            _canonical_fact(
                subject=subject,
                predicate=predicate,
                value=value,
                certainty=_certainty_for_fact(item),
                source=source,
            )
        )

    for memory in world.accessible_memories():
        if not memory.predicate or memory.value is None:
            continue
        certainty = "CLAIMED" if memory.kind == "claim" else "TRUE"
        candidates.append(
            _canonical_fact(
                subject=memory.subject,
                predicate=memory.predicate,
                value=str(memory.value),
                certainty=certainty,
                source=memory.source,
                fact_id=f"fact.{memory.memory_id}",
            )
        )

    claim_values = {
        str(item["value"])
        for item in candidates
        if item.get("predicate") == "claimed_name" and item.get("value")
    }
    identity_subject = world.visitor_id or "visitor.unknown"
    if not claim_values:
        candidates.append(
            _canonical_fact(
                subject=identity_subject,
                predicate="identity_status",
                value="UNKNOWN",
                certainty="UNKNOWN",
                source="identity_rule",
                fact_id="fact.identity-status.unknown",
                derived=True,
            )
        )
    elif len(claim_values) >= 2:
        candidates.append(
            _canonical_fact(
                subject=identity_subject,
                predicate="identity_status",
                value="CONFLICTED",
                certainty="CONFLICTED",
                source="identity_rule",
                fact_id="fact.identity-status.conflicted",
                derived=True,
            )
        )

    for residue in sorted(set(world.emotional_residue)):
        candidates.append(
            _canonical_fact(
                subject=world.actor.character_id,
                predicate="emotion",
                value=residue,
                certainty="TRUE",
                source="emotional_residue",
                fact_id=f"fact.emotion.{sha256(residue.encode('utf-8')).hexdigest()[:12]}",
                derived=True,
            )
        )

    completion = task_spec.completion if task_spec is not None else {}
    if (
        completion.get("type") == "report_predicate"
        and completion.get("predicate") == "refusal"
        and isinstance(completion.get("value"), str)
    ):
        value = completion["value"]
        candidates.append(
            _canonical_fact(
                subject=world.actor.character_id,
                predicate="refusal",
                value=value,
                certainty="TRUE",
                source="character_rule",
                fact_id=f"fact.refusal.{sha256(value.encode('utf-8')).hexdigest()[:12]}",
                derived=True,
            )
        )

    deduped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for fact in candidates:
        key = (
            str(fact["subject"]),
            str(fact["predicate"]),
            str(fact["value"]),
            str(fact["certainty"]),
            str(fact["source"]),
        )
        deduped.setdefault(key, fact)
    return tuple(sorted(deduped.values(), key=lambda item: item["fact_id"]))


def reportable_fact_map(
    world: WorldState,
    task: ActiveTask | TaskSpec | None = None,
) -> dict[str, dict[str, Any]]:
    return {fact["fact_id"]: fact for fact in derive_reportable_facts(world, task)}


def model_visible_reportable_facts(
    world: WorldState,
    task: ActiveTask | TaskSpec | None = None,
) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for fact in derive_reportable_facts(world, task):
        item = dict(fact)
        item["subject"] = world.model_target_id(str(item["subject"]))
        visible.append(item)
    return visible


def resolve_fact_ids(
    fact_ids: Iterable[str],
    *,
    world: WorldState,
    task: ActiveTask | TaskSpec | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    catalog = reportable_fact_map(world, task)
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for fact_id in fact_ids:
        fact = catalog.get(fact_id)
        if fact is None:
            missing.append(fact_id)
            continue
        payload = {key: value for key, value in fact.items() if key not in {"fact_id", "derived"}}
        resolved.append(payload)
    return resolved, missing


def completion_progress(
    task: ActiveTask,
    world: WorldState,
) -> dict[str, Any]:
    catalog = derive_reportable_facts(world, task)
    completion = task.spec.completion
    accepted: list[str] = []
    description = "Deliver a grounded report to the player."

    if completion:
        kind = completion.get("type", "report_predicate")
        if kind in {"report_predicate", "report_fact"}:
            predicate = completion.get("predicate")
            value = completion.get("value")
            certainty = completion.get("certainty")
            accepted = [
                item["fact_id"]
                for item in catalog
                if item.get("predicate") == predicate
                and (value is None or item.get("value") == value)
                and (certainty is None or item.get("certainty") == certainty)
            ]
            description = f"Report one catalog fact with predicate={predicate!r}"
            if value is not None:
                description += f" and value={value!r}"
            description += "."
        elif kind == "report_conflict":
            accepted = [
                item["fact_id"]
                for item in catalog
                if item.get("predicate") in {"claimed_name", "identity_status"}
            ]
            description = (
                "Report all accessible conflicting claimed_name facts. "
                "The runtime derives conflict status; do not choose one claim as truth."
            )
    elif task.spec.required_report_fact is not None:
        accepted = [
            item["fact_id"]
            for item in catalog
            if item.get("predicate") == "claimed_name"
            and item.get("value") == task.spec.required_report_fact
            and item.get("certainty") == "CLAIMED"
        ]
        description = "Report the accessible source-qualified claimed_name fact."

    near_player = world.actor.location == world.player_location
    door_closed = world.objects.get("door.front") is None or world.objects["door.front"].state == "closed"
    remaining: list[str] = []
    if not accepted:
        remaining.append("obtain or select a matching reportable fact; do not invent one")
    if not near_player:
        remaining.append("move_to(player) before report")
    if not door_closed:
        remaining.append("the front door must be closed")

    return {
        "schema_version": "wangsheng.completion_progress.v1",
        "completion_action": "report",
        "description": description,
        "accepted_fact_ids": accepted,
        "ready_to_complete": bool(accepted and near_player and door_closed),
        "remaining_requirements": remaining,
        "stop_after_success": True,
    }
