from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BridgeErrorCode(str, Enum):
    PROTOCOL_VERSION_UNSUPPORTED = "PROTOCOL_VERSION_UNSUPPORTED"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    UNKNOWN_MESSAGE_KIND = "UNKNOWN_MESSAGE_KIND"
    DUPLICATE_MESSAGE_CONFLICT = "DUPLICATE_MESSAGE_CONFLICT"
    DUPLICATE_ACTION_CONFLICT = "DUPLICATE_ACTION_CONFLICT"
    STALE_WORLD_EPOCH = "STALE_WORLD_EPOCH"
    STALE_WORLD_VERSION = "STALE_WORLD_VERSION"
    STALE_TASK_GENERATION = "STALE_TASK_GENERATION"
    GAME_PAUSED = "GAME_PAUSED"
    ACTOR_NOT_FOUND = "ACTOR_NOT_FOUND"
    ACTOR_BUSY = "ACTOR_BUSY"
    ACTION_NOT_SUPPORTED = "ACTION_NOT_SUPPORTED"
    ACTION_PRECONDITION_FAILED = "ACTION_PRECONDITION_FAILED"
    TARGET_GONE = "TARGET_GONE"
    NO_PATH = "NO_PATH"
    LOCKED = "LOCKED"
    CANCELLED_BY_PLAYER = "CANCELLED_BY_PLAYER"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    SAVE_CORRUPTED = "SAVE_CORRUPTED"
    SAVE_VERSION_UNSUPPORTED = "SAVE_VERSION_UNSUPPORTED"
    DELTA_SEQUENCE_GAP = "DELTA_SEQUENCE_GAP"
    STATE_DIGEST_MISMATCH = "STATE_DIGEST_MISMATCH"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INTERNAL_BRIDGE_ERROR = "INTERNAL_BRIDGE_ERROR"


@dataclass(slots=True)
class BridgeProtocolError(Exception):
    code: BridgeErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "error_code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }
