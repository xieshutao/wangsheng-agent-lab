from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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

    def target_exists(self, target: str) -> bool:
        return target in self.objects or target in {
            self.actor.character_id,
            "player",
            self.visitor_id,
        }

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
        }


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    command: str
    allowed_actions: frozenset[str]
    forbidden_actions: frozenset[str]
    required_report_fact: str | None
    hard_constraints: frozenset[str] = frozenset()
    max_steps: int = 12


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
