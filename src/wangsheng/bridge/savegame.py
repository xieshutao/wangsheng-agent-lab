from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .errors import BridgeErrorCode, BridgeProtocolError
from .protocol import SAVE_SCHEMA_VERSION, canonical_json, gameplay_digest


@dataclass(frozen=True, slots=True)
class SaveGame:
    schema_version: str
    world_id: str
    gameplay_state: dict[str, Any]
    gameplay_digest: str

    @classmethod
    def create(cls, *, world_id: str, gameplay_state: dict[str, Any]) -> "SaveGame":
        return cls(
            schema_version=SAVE_SCHEMA_VERSION,
            world_id=world_id,
            gameplay_state=gameplay_state,
            gameplay_digest=gameplay_digest(gameplay_state),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SaveGame":
        if payload.get("schema_version") != SAVE_SCHEMA_VERSION:
            raise BridgeProtocolError(
                BridgeErrorCode.SAVE_VERSION_UNSUPPORTED,
                f"Unsupported save schema {payload.get('schema_version')!r}.",
            )
        state = payload.get("gameplay_state")
        if not isinstance(state, dict):
            raise BridgeProtocolError(
                BridgeErrorCode.SAVE_CORRUPTED,
                "Save gameplay_state must be an object.",
            )
        expected = gameplay_digest(state)
        actual = payload.get("gameplay_digest")
        if actual != expected:
            raise BridgeProtocolError(
                BridgeErrorCode.SAVE_CORRUPTED,
                "Save gameplay digest does not match its canonical state.",
                {"expected": expected, "actual": actual},
            )
        world_id = payload.get("world_id")
        if not isinstance(world_id, str) or not world_id:
            raise BridgeProtocolError(
                BridgeErrorCode.SAVE_CORRUPTED,
                "Save world_id must be a non-empty string.",
            )
        return cls(SAVE_SCHEMA_VERSION, world_id, state, expected)

    @classmethod
    def from_json(cls, text: str) -> "SaveGame":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BridgeProtocolError(
                BridgeErrorCode.SAVE_CORRUPTED,
                "Save is not valid JSON.",
                {"line": exc.lineno, "column": exc.colno},
            ) from exc
        if not isinstance(payload, dict):
            raise BridgeProtocolError(
                BridgeErrorCode.SAVE_CORRUPTED,
                "Save root must be an object.",
            )
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "world_id": self.world_id,
            "gameplay_state": self.gameplay_state,
            "gameplay_digest": self.gameplay_digest,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())
