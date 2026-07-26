from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from .contracts import Intent, MemoryEvent


class TaskStatus(str, Enum):
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Action:
    name: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    action_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "target": self.target,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class Observation:
    success: bool
    code: str
    message: str
    action: Action
    source: str = "runtime"
    world_delta: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "action": self.action.to_dict(),
            "world_delta": dict(self.world_delta),
            "evidence": dict(self.evidence),
        }


@dataclass(slots=True)
class WorldObject:
    object_id: str
    object_type: str
    location: str
    state: str
    interactable: bool = True
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CharacterState:
    character_id: str
    location: str
    known_targets: set[str] = field(default_factory=set)
    permissions: set[str] = field(default_factory=set)


@dataclass(slots=True)
class WorldState:
    actor: CharacterState
    player_location: str
    objects: dict[str, WorldObject]
    visitor_id: str | None = None
    visitor_claimed_name: str | None = None
    visitor_responses: list[str | None] = field(default_factory=list)
    heard_events: list[str] = field(default_factory=list)
    conversation_facts: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    time_seconds: float = 0.0
    memory_events: list[MemoryEvent] = field(default_factory=list)
    emotional_residue: list[str] = field(default_factory=list)
    forced_action_results: dict[str, list[str]] = field(default_factory=dict)
    model_target_aliases: dict[str, str] = field(default_factory=dict)

    def target_exists(self, target: str) -> bool:
        canonical = self.canonical_target_id(target)
        return canonical in self.objects or canonical in {
            self.actor.character_id,
            "player",
            self.visitor_id,
        }

    def accessible_memories(self) -> list[MemoryEvent]:
        return [memory for memory in self.memory_events if memory.is_context_accessible]

    def has_accessible_fact(self, *, predicate: str, value: str | None = None) -> bool:
        for fact in self.conversation_facts:
            if fact.get("predicate") == predicate and (
                value is None or fact.get("value") == value
            ):
                return True
        for memory in self.accessible_memories():
            if memory.predicate == predicate and (value is None or memory.value == value):
                return True
        return False

    def model_target_id(self, canonical_target: str) -> str:
        for alias, canonical in self.model_target_aliases.items():
            if canonical == canonical_target:
                return alias
        return canonical_target

    def canonical_target_id(self, target: str) -> str:
        return self.model_target_aliases.get(target, target)

    def canonicalize_action(self, action: Action) -> Action:
        target = self.canonical_target_id(action.target) if action.target else None
        parameters = dict(action.parameters)
        barrier_id = parameters.get("barrier_id")
        if isinstance(barrier_id, str):
            parameters["barrier_id"] = self.canonical_target_id(barrier_id)
        facts = parameters.get("facts")
        if isinstance(facts, list):
            canonical_facts: list[Any] = []
            for fact in facts:
                if not isinstance(fact, dict):
                    canonical_facts.append(fact)
                    continue
                canonical_fact = dict(fact)
                subject = canonical_fact.get("subject")
                if isinstance(subject, str):
                    canonical_fact["subject"] = self.canonical_target_id(subject)
                canonical_facts.append(canonical_fact)
            parameters["facts"] = canonical_facts
        if target == action.target and parameters == action.parameters:
            return action
        return replace(action, target=target, parameters=parameters)

    def context_snapshot(self) -> dict[str, Any]:
        """Return only information the actor may expose to a model.

        This deliberately differs from :meth:`snapshot`, which is the
        authoritative save/debug representation. Hidden identity fields,
        simulator queues and canonical IDs that encode secret information are
        never emitted here.
        """

        known_canonical = set(self.actor.known_targets)
        known_targets = sorted(self.model_target_id(target) for target in known_canonical)
        visible_objects: dict[str, dict[str, Any]] = {}
        for canonical_id, value in sorted(self.objects.items()):
            if canonical_id not in known_canonical:
                continue
            visible_id = self.model_target_id(canonical_id)
            visible_objects[visible_id] = {
                "object_type": value.object_type,
                "location": value.location,
                "state": value.state,
                "interactable": value.interactable,
                "properties": dict(sorted(value.properties.items())),
            }

        visible_facts = [self._model_visible_fact(fact) for fact in self.conversation_facts]
        visible_memories = [
            self._model_visible_memory(memory) for memory in self.accessible_memories()
        ]
        visible_entities: dict[str, dict[str, Any]] = {}
        for canonical_id in sorted(known_canonical):
            if canonical_id in self.objects or canonical_id in {
                "player",
                self.actor.character_id,
            }:
                continue
            visible_id = self.model_target_id(canonical_id)
            entity_type = "visitor" if canonical_id == self.visitor_id else "entity"
            claims = [
                item
                for item in [*visible_facts, *visible_memories]
                if item.get("subject") == visible_id
                and item.get("predicate") == "claimed_name"
            ]
            distinct_claims = sorted(
                {str(fact.get("value")) for fact in claims if fact.get("value")}
            )
            identity_status = (
                "conflicted"
                if len(distinct_claims) > 1
                else "claimed"
                if distinct_claims
                else "unknown"
            )
            visible_entities[visible_id] = {
                "entity_type": entity_type,
                "presence": "known",
                "identity_status": identity_status,
            }

        payload = {
            "schema_version": "wangsheng.model_visible_world.v1",
            "actor": {
                "character_id": self.actor.character_id,
                "location": self.actor.location,
                "known_targets": known_targets,
                "permissions": sorted(self.actor.permissions),
            },
            "player": {"target_id": "player", "location": self.player_location},
            "objects": visible_objects,
            "entities": visible_entities,
            "heard_events": list(self.heard_events),
            "conversation_facts": visible_facts,
            "memory_events": visible_memories,
            "emotional_residue": list(self.emotional_residue),
            "time_seconds": self.time_seconds,
        }
        return self._sanitize_model_value(payload)

    def _model_visible_fact(self, fact: dict[str, Any]) -> dict[str, Any]:
        payload = dict(fact)
        subject = payload.get("subject")
        if isinstance(subject, str):
            payload["subject"] = self.model_target_id(subject)
        return payload

    def _model_visible_memory(self, memory: MemoryEvent) -> dict[str, Any]:
        payload = memory.to_dict()
        payload["subject"] = self.model_target_id(memory.subject)
        return payload

    def _sanitize_model_value(self, value: Any) -> Any:
        if isinstance(value, str):
            sanitized = value
            for alias, canonical in self.model_target_aliases.items():
                sanitized = sanitized.replace(canonical, alias)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_model_value(item) for item in value]
        if isinstance(value, dict):
            return {
                self._sanitize_model_value(key): self._sanitize_model_value(item)
                for key, item in value.items()
            }
        return value

    def snapshot(self) -> dict[str, Any]:
        return {
            "actor": {
                "character_id": self.actor.character_id,
                "location": self.actor.location,
                "known_targets": sorted(self.actor.known_targets),
                "permissions": sorted(self.actor.permissions),
            },
            "player_location": self.player_location,
            "objects": {
                key: {
                    "object_type": value.object_type,
                    "location": value.location,
                    "state": value.state,
                    "interactable": value.interactable,
                    "properties": dict(sorted(value.properties.items())),
                }
                for key, value in sorted(self.objects.items())
            },
            "visitor_id": self.visitor_id,
            "visitor_claimed_name": self.visitor_claimed_name,
            "visitor_responses_remaining": len(self.visitor_responses),
            "heard_events": list(self.heard_events),
            "conversation_facts": list(self.conversation_facts),
            "reports": list(self.reports),
            "time_seconds": self.time_seconds,
            "memory_events": [memory.to_dict() for memory in self.memory_events],
            "emotional_residue": list(self.emotional_residue),
            "forced_action_results": {
                key: list(value) for key, value in sorted(self.forced_action_results.items())
            },
            "model_target_aliases": dict(sorted(self.model_target_aliases.items())),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "WorldState":
        actor_payload = snapshot["actor"]
        return cls(
            actor=CharacterState(
                actor_payload["character_id"],
                actor_payload["location"],
                set(actor_payload.get("known_targets", [])),
                set(actor_payload.get("permissions", [])),
            ),
            player_location=snapshot["player_location"],
            objects={
                object_id: WorldObject(
                    object_id,
                    payload["object_type"],
                    payload["location"],
                    payload["state"],
                    payload.get("interactable", True),
                    dict(payload.get("properties", {})),
                )
                for object_id, payload in snapshot["objects"].items()
            },
            visitor_id=snapshot.get("visitor_id"),
            visitor_claimed_name=snapshot.get("visitor_claimed_name"),
            visitor_responses=[None]
            * int(snapshot.get("visitor_responses_remaining", 0)),
            heard_events=list(snapshot.get("heard_events", [])),
            conversation_facts=list(snapshot.get("conversation_facts", [])),
            reports=list(snapshot.get("reports", [])),
            time_seconds=float(snapshot.get("time_seconds", 0.0)),
            memory_events=[
                MemoryEvent.from_dict(item) for item in snapshot.get("memory_events", [])
            ],
            emotional_residue=list(snapshot.get("emotional_residue", [])),
            forced_action_results={
                key: list(value)
                for key, value in snapshot.get("forced_action_results", {}).items()
            },
            model_target_aliases=dict(snapshot.get("model_target_aliases", {})),
        )


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    command: str
    allowed_actions: frozenset[str]
    forbidden_actions: frozenset[str]
    required_report_fact: str | None
    hard_constraints: frozenset[str] = frozenset()
    max_steps: int = 12
    completion: dict[str, Any] = field(default_factory=dict)
    intent: Intent | None = None


@dataclass(slots=True)
class ActiveTask:
    spec: TaskSpec
    status: TaskStatus = TaskStatus.ACTIVE
    step_count: int = 0
    observations: list[Observation] = field(default_factory=list)
    terminal_reason: str | None = None
    fingerprint_counts: dict[str, int] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status is not TaskStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class PolicyContext:
    command: str
    task_id: str
    step_count: int
    available_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    world: dict[str, Any]
    observations: tuple[dict[str, Any], ...]
    tool_schemas: tuple[dict[str, Any], ...] = ()
    intent: dict[str, Any] = field(default_factory=dict)
    current_affordances: dict[str, Any] = field(default_factory=dict)

    @property
    def authorized_actions(self) -> tuple[str, ...]:
        return self.available_actions
