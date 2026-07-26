from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from .errors import BridgeErrorCode, BridgeProtocolError
from .protocol import PROTOCOL_VERSION, canonical_json, content_fingerprint


class MessageKind(str, Enum):
    HELLO = "HELLO"
    HELLO_ACK = "HELLO_ACK"
    WORLD_SNAPSHOT = "WORLD_SNAPSHOT"
    WORLD_DELTA = "WORLD_DELTA"
    WORLD_EVENT = "WORLD_EVENT"
    HEARTBEAT = "HEARTBEAT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_TERMINATED = "TASK_TERMINATED"
    ACTION_REQUESTED = "ACTION_REQUESTED"
    ACTION_ACCEPTED = "ACTION_ACCEPTED"
    ACTION_REJECTED = "ACTION_REJECTED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_CANCEL_REQUESTED = "ACTION_CANCEL_REQUESTED"
    ACTION_CANCELLED = "ACTION_CANCELLED"
    ACTION_EXPIRED = "ACTION_EXPIRED"
    GAME_PAUSED = "GAME_PAUSED"
    GAME_RESUMED = "GAME_RESUMED"
    SAVE_REQUESTED = "SAVE_REQUESTED"
    SAVE_COMPLETED = "SAVE_COMPLETED"
    LOAD_REQUESTED = "LOAD_REQUESTED"
    LOAD_COMPLETED = "LOAD_COMPLETED"
    WORLD_RESET = "WORLD_RESET"


@dataclass(frozen=True, slots=True)
class BridgeMessage:
    protocol_version: str
    message_id: str
    message_kind: MessageKind
    session_id: str
    world_id: str
    world_epoch: str
    world_version: int
    sequence: int
    virtual_time_ms: int
    payload: dict[str, Any] = field(default_factory=dict)
    tick_id: str | None = None
    task_id: str | None = None
    action_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "protocol_version",
            "message_id",
            "message_kind",
            "session_id",
            "world_id",
            "world_epoch",
            "world_version",
            "sequence",
            "tick_id",
            "task_id",
            "action_id",
            "correlation_id",
            "causation_id",
            "virtual_time_ms",
            "payload",
        }
    )
    _REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {
            "protocol_version",
            "message_id",
            "message_kind",
            "session_id",
            "world_id",
            "world_epoch",
            "world_version",
            "sequence",
            "virtual_time_ms",
            "payload",
        }
    )

    def __post_init__(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise BridgeProtocolError(
                BridgeErrorCode.PROTOCOL_VERSION_UNSUPPORTED,
                f"Expected protocol {PROTOCOL_VERSION}, got {self.protocol_version!r}.",
            )
        for field_name in ("message_id", "session_id", "world_id", "world_epoch"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise BridgeProtocolError(
                    BridgeErrorCode.SCHEMA_INVALID,
                    f"{field_name} must be a non-empty string.",
                )
        if not isinstance(self.world_version, int) or self.world_version < 0:
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "world_version must be a non-negative integer.",
            )
        if not isinstance(self.sequence, int) or self.sequence < 0:
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "sequence must be a non-negative integer.",
            )
        if not isinstance(self.virtual_time_ms, int) or self.virtual_time_ms < 0:
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "virtual_time_ms must be a non-negative integer.",
            )
        if not isinstance(self.payload, dict):
            raise BridgeProtocolError(BridgeErrorCode.SCHEMA_INVALID, "payload must be an object.")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BridgeMessage":
        if not isinstance(value, dict):
            raise BridgeProtocolError(BridgeErrorCode.SCHEMA_INVALID, "Message must be an object.")
        unknown = set(value) - cls._FIELDS
        missing = cls._REQUIRED - set(value)
        if unknown:
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "Unknown message fields are not allowed.",
                {"unknown_fields": sorted(unknown)},
            )
        if missing:
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "Required message fields are missing.",
                {"missing_fields": sorted(missing)},
            )
        try:
            kind = MessageKind(value["message_kind"])
        except (TypeError, ValueError) as exc:
            raise BridgeProtocolError(
                BridgeErrorCode.UNKNOWN_MESSAGE_KIND,
                f"Unknown message kind {value.get('message_kind')!r}.",
            ) from exc
        return cls(
            protocol_version=value["protocol_version"],
            message_id=value["message_id"],
            message_kind=kind,
            session_id=value["session_id"],
            world_id=value["world_id"],
            world_epoch=value["world_epoch"],
            world_version=value["world_version"],
            sequence=value["sequence"],
            tick_id=value.get("tick_id"),
            task_id=value.get("task_id"),
            action_id=value.get("action_id"),
            correlation_id=value.get("correlation_id"),
            causation_id=value.get("causation_id"),
            virtual_time_ms=value["virtual_time_ms"],
            payload=dict(value["payload"]),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "message_kind": self.message_kind.value,
            "session_id": self.session_id,
            "world_id": self.world_id,
            "world_epoch": self.world_epoch,
            "world_version": self.world_version,
            "sequence": self.sequence,
            "virtual_time_ms": self.virtual_time_ms,
            "payload": dict(self.payload),
        }
        for name in ("tick_id", "task_id", "action_id", "correlation_id", "causation_id"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        return result

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())
