from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .contracts import Intent, MemoryAccess, MemoryEvent


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

    def target_exists(self, target: str) -> bool:
        return target in self.objects or target in {
            self.actor.character_id,
            "player",
            self.visitor_id,
        }

    def accessible_memories(self) -> list[MemoryEvent]:
        return [memory for memory in self.memory_events if memory.is_context_accessible]

    def has_accessible_fact(self, *, predicate: str, value: str | None = None) -> bool:
        for fact in self.conversation_facts:
            if fact.get("predicate") == predicate and (value is None or fact.get("value") == value):
                return True
        for memory in self.accessible_memories():
            if memory.predicate == predicate and (value is None or memory.value == value):
                return True
        return False

    def context_snapshot(self) -> dict[str, Any]:
        payload = self.snapshot()
        payload["memory_events"] = [memory.to_dict() for memory in self.accessible_memories()]
        payload.pop("forced_action_results", None)
        return payload

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
            "forced_action_results": {key: list(value) for key, value in sorted(self.forced_action_results.items())},
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
            visitor_responses=[None] * int(snapshot.get("visitor_responses_remaining", 0)),
            heard_events=list(snapshot.get("heard_events", [])),
            conversation_facts=list(snapshot.get("conversation_facts", [])),
            reports=list(snapshot.get("reports", [])),
            time_seconds=float(snapshot.get("time_seconds", 0.0)),
            memory_events=[MemoryEvent.from_dict(item) for item in snapshot.get("memory_events", [])],
            emotional_residue=list(snapshot.get("emotional_residue", [])),
            forced_action_results={key: list(value) for key, value in snapshot.get("forced_action_results", {}).items()},
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
