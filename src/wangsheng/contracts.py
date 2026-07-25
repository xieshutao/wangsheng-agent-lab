from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntentKind(str, Enum):
    TASK = "task"
    CHAT = "chat"
    REFUSAL = "refusal"


class MemoryAccess(str, Enum):
    CLEAR = "CLEAR"
    FUZZY = "FUZZY"
    SUPPRESSED = "SUPPRESSED"
    REWRITTEN = "REWRITTEN"
    FORGOTTEN = "FORGOTTEN"
    SEALED = "SEALED"


@dataclass(frozen=True, slots=True)
class Intent:
    intent_id: str
    kind: IntentKind
    text: str
    source: str = "player"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.intent.v1",
            "intent_id": self.intent_id,
            "kind": self.kind.value,
            "text": self.text,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action_id: str
    name: str
    target_id: str | None
    arguments: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_action(cls, action: Any) -> "ActionRequest":
        return cls(
            action_id=action.action_id or "",
            name=action.name,
            target_id=action.target,
            arguments=dict(action.parameters),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.action_request.v1",
            "action_id": self.action_id,
            "name": self.name,
            "target_id": self.target_id,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    status: str
    reason_code: str
    message: str
    source: str
    world_delta: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_observation(cls, observation: Any) -> "ActionResult":
        return cls(
            action_id=observation.action.action_id or "",
            status="success" if observation.success else "failure",
            reason_code=observation.code,
            message=observation.message,
            source=observation.source,
            world_delta=dict(observation.world_delta),
            evidence=dict(observation.evidence),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.action_result.v1",
            "action_id": self.action_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
            "source": self.source,
            "world_delta": dict(self.world_delta),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class MemoryEvent:
    memory_id: str
    subject: str
    kind: str
    content: str
    source: str
    access: MemoryAccess = MemoryAccess.CLEAR
    confidence: float = 1.0
    version: int = 1
    predicate: str | None = None
    value: str | None = None

    @property
    def is_context_accessible(self) -> bool:
        return self.access not in {
            MemoryAccess.SUPPRESSED,
            MemoryAccess.FORGOTTEN,
            MemoryAccess.SEALED,
        }

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": "wangsheng.memory_event.v1",
            "memory_id": self.memory_id,
            "subject": self.subject,
            "kind": self.kind,
            "source": self.source,
            "access": self.access.value,
            "confidence": self.confidence,
            "version": self.version,
            "predicate": self.predicate,
            "value": self.value,
        }
        if include_content:
            payload["content"] = self.content
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryEvent":
        return cls(
            memory_id=payload["memory_id"],
            subject=payload["subject"],
            kind=payload["kind"],
            content=payload.get("content", ""),
            source=payload["source"],
            access=MemoryAccess(payload.get("access", "CLEAR")),
            confidence=float(payload.get("confidence", 1.0)),
            version=int(payload.get("version", 1)),
            predicate=payload.get("predicate"),
            value=payload.get("value"),
        )


@dataclass(frozen=True, slots=True)
class TraceEvent:
    episode_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.trace_event.v1",
            "episode_id": self.episode_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": dict(self.payload),
        }
