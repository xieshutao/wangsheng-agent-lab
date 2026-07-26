from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Iterable

from .models import ActiveTask, Observation, TaskSpec, WorldState


_FACT_ACTION_HINTS: dict[str, tuple[dict[str, Any], ...]] = {
    "claimed_name": (
        {"action": "ask_through", "arguments": {"topic": "identity"}, "produces": ["claimed_name"]},
    ),
    "visit_purpose": (
        {"action": "ask_through", "arguments": {"topic": "purpose"}, "produces": ["visit_purpose"]},
    ),
    "visitor_request": (
        {"action": "ask_through", "arguments": {"topic": "request"}, "produces": ["visitor_request"]},
    ),
    "door_state": (
        {"action": "ask_through", "arguments": {"topic": "door_state"}, "produces": ["door_state"]},
        {"action": "observe", "arguments": {}, "produces": ["door_state"]},
    ),
    "presence": (
        {"action": "listen_at", "arguments": {}, "produces": ["presence"]},
    ),
}


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


def required_fact_types(task: ActiveTask | TaskSpec) -> tuple[str, ...]:
    spec = task.spec if isinstance(task, ActiveTask) else task
    completion = spec.completion
    if completion:
        kind = completion.get("type", "report_predicate")
        if kind in {"report_predicate", "report_fact"}:
            predicate = completion.get("predicate")
            return (str(predicate),) if isinstance(predicate, str) and predicate else ()
        if kind == "report_conflict":
            return ("claimed_name",)
    if spec.required_report_fact is not None:
        return ("claimed_name",)
    return ()


def evidence_action_hints(required_types: Iterable[str]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fact_type in required_types:
        for hint in _FACT_ACTION_HINTS.get(fact_type, ()):
            key = json.dumps(hint, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen.add(key)
                hints.append(dict(hint))
    return hints


def render_report_text(
    facts: Iterable[dict[str, Any]],
    *,
    tone: str = "neutral",
) -> str:
    """Render player-visible factual text from trusted structured facts.

    The model may choose a bounded tone enum, but it never authors the factual
    proposition. Unknown predicates fall back to a literal predicate/value form
    so the renderer cannot silently invent semantics.
    """

    fact_list = list(facts)
    clauses = [_render_fact_clause(fact) for fact in fact_list]
    body = " ".join(clause for clause in clauses if clause).strip()
    if not body:
        body = "No grounded fact is available to report."
    if tone == "formal":
        return f"Report: {body}"
    if tone == "gentle":
        return f"I should tell you this carefully: {body}"
    return body


def _render_fact_clause(fact: dict[str, Any]) -> str:
    predicate = str(fact.get("predicate") or "fact")
    value = str(fact.get("value") or "")
    certainty = str(fact.get("certainty") or "TRUE")
    if predicate == "claimed_name":
        return f"The visitor claims to be {value}."
    if predicate == "visit_purpose":
        if value == "speak_with_player":
            return "The visitor says they are here to speak with you."
        return f"The visitor states their purpose as {value}."
    if predicate == "visitor_request":
        if value == "notify_player_of_arrival":
            return "The visitor asks me to notify you of their arrival."
        return f"The visitor requests: {value}."
    if predicate == "presence":
        if value == "waiting_outside_closed_front_door":
            return "Someone is waiting outside the closed front door."
        return f"Presence status: {value}."
    if predicate == "door_state":
        return f"The front door is {value}."
    if predicate == "identity_status":
        if value == "UNKNOWN":
            return "The visitor's identity is unknown."
        if value == "CONFLICTED":
            return "The available identity claims conflict."
        return f"The visitor's identity status is {value}."
    if predicate == "emotion":
        return f"An emotional residue remains: {value}."
    if predicate == "refusal":
        return f"I must refuse this request: {value}."
    qualifier = "claims" if certainty == "CLAIMED" else "reports"
    return f"The source {qualifier} {predicate}={value}."


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

    required = list(required_fact_types(task))
    available_predicates = {str(item.get("predicate")) for item in catalog}
    satisfied = sorted(item for item in required if item in available_predicates and bool(accepted))
    missing = sorted(set(required) - set(satisfied))

    near_player = world.actor.location == world.player_location
    door_closed = world.objects.get("door.front") is None or world.objects["door.front"].state == "closed"
    remaining: list[str] = []
    if not accepted:
        remaining.append("obtain or select a matching reportable fact; do not invent one")
    if not near_player:
        remaining.append("move_to(player) before report")
    if not door_closed:
        remaining.append("the front door must be closed")

    recovery = _recovery_guidance(task, missing or required)
    return {
        "schema_version": "wangsheng.completion_progress.v2",
        "completion_action": "report",
        "description": description,
        "required_fact_types": required,
        "satisfied_fact_types": satisfied,
        "missing_fact_types": missing,
        "accepted_fact_ids": accepted,
        "evidence_action_hints": evidence_action_hints(missing or required),
        "ready_to_complete": bool(accepted and near_player and door_closed),
        "report_would_complete": bool(accepted and near_player and door_closed),
        "remaining_requirements": remaining,
        "recovery_guidance": recovery,
        "stop_after_success": True,
    }


def _recovery_guidance(
    task: ActiveTask,
    required_types: Iterable[str],
) -> dict[str, Any]:
    observations = task.observations
    reasons: list[str] = []
    avoid: list[dict[str, Any]] = []

    recent = observations[-5:]
    trailing_no_evidence = 0
    for observation in reversed(recent):
        if _observation_added_evidence(observation):
            break
        trailing_no_evidence += 1

    report_observations = [
        item
        for item in recent
        if item.success and item.action.name == "report"
    ]
    if report_observations and not task.is_terminal:
        latest = report_observations[-1]
        reasons.append("successful_report_did_not_complete_task")
        fact_ids = latest.action.parameters.get("fact_ids")
        if isinstance(fact_ids, list):
            avoid.append({"action": "report", "fact_ids": sorted(str(item) for item in fact_ids)})

    move_targets = [
        item.action.target
        for item in recent
        if item.action.name == "move_to" and item.action.target is not None
    ]
    if len(move_targets) >= 4 and move_targets[-4] == move_targets[-2] and move_targets[-3] == move_targets[-1]:
        reasons.append("movement_oscillation_without_new_evidence")
        avoid.extend(
            {"action": "move_to", "target_id": target}
            for target in sorted({move_targets[-1], move_targets[-2]})
        )

    if trailing_no_evidence >= 3:
        reasons.append("three_or_more_steps_without_new_evidence")

    latest_failure = next((item for item in reversed(recent) if not item.success), None)
    if latest_failure is not None and latest_failure.code in {"TIMEOUT", "NO_PATH", "LOCKED", "TOO_FAR"}:
        reasons.append(f"recover_after_{latest_failure.code.lower()}")

    active = bool(reasons)
    instruction = (
        "Do not repeat the listed no-progress actions. Choose an executable action that can "
        "produce one of the missing fact types, using evidence_action_hints."
        if active
        else "No recovery intervention is active."
    )
    return {
        "schema_version": "wangsheng.recovery_guidance.v1",
        "active": active,
        "reason_codes": sorted(set(reasons)),
        "trailing_steps_without_new_evidence": trailing_no_evidence,
        "avoid_semantic_actions": avoid,
        "preferred_evidence_actions": evidence_action_hints(required_types),
        "instruction": instruction,
    }


def _observation_added_evidence(observation: Observation) -> bool:
    if not observation.success:
        return False
    if observation.action.name in {"ask_through", "listen_at", "observe"}:
        return bool(observation.evidence)
    return bool(observation.world_delta and observation.action.name not in {"move_to", "report", "wait"})
