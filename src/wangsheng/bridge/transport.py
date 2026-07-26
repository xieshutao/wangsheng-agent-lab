from __future__ import annotations

import json
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .errors import BridgeErrorCode, BridgeProtocolError
from .messages import BridgeMessage, MessageKind
from .protocol import apply_json_operations, gameplay_digest


@dataclass(slots=True)
class InMemoryTransport:
    _queue: deque[BridgeMessage] = field(default_factory=deque)
    sent: list[BridgeMessage] = field(default_factory=list)

    def send(self, message: BridgeMessage) -> None:
        self.sent.append(message)
        self._queue.append(message)

    def receive(self) -> BridgeMessage | None:
        return self._queue.popleft() if self._queue else None

    def duplicate(self, index: int = -1) -> None:
        self._queue.append(self.sent[index])

    def drop_next(self) -> BridgeMessage | None:
        return self._queue.popleft() if self._queue else None

    def reorder_next_two(self) -> None:
        if len(self._queue) < 2:
            return
        first = self._queue.popleft()
        second = self._queue.popleft()
        self._queue.appendleft(first)
        self._queue.appendleft(second)


@dataclass(slots=True)
class JsonlTraceTransport:
    path: Path

    def append(self, message: BridgeMessage) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(message.canonical_json())
            handle.write("\n")

    def read_all(self) -> list[BridgeMessage]:
        messages: list[BridgeMessage] = []
        if not self.path.exists():
            return messages
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    messages.append(BridgeMessage.from_dict(payload))
                except (json.JSONDecodeError, BridgeProtocolError) as exc:
                    raise BridgeProtocolError(
                        BridgeErrorCode.SCHEMA_INVALID,
                        f"Malformed JSONL trace at line {line_number}: {exc}",
                    ) from exc
        return messages


@dataclass(frozen=True, slots=True)
class ReplayResult:
    passed: bool
    message_count: int
    final_world_version: int | None
    final_digest: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "message_count": self.message_count,
            "final_world_version": self.final_world_version,
            "final_digest": self.final_digest,
            "errors": list(self.errors),
        }


def replay_message_stream(messages: Iterable[BridgeMessage]) -> ReplayResult:
    errors: list[str] = []
    state: dict[str, object] | None = None
    current_epoch: str | None = None
    current_version: int | None = None
    previous_sequence: int | None = None
    count = 0
    final_digest_value: str | None = None
    for message in messages:
        count += 1
        if previous_sequence is not None and message.sequence != previous_sequence + 1:
            errors.append(
                f"{BridgeErrorCode.DELTA_SEQUENCE_GAP.value}: expected sequence "
                f"{previous_sequence + 1}, got {message.sequence}"
            )
        previous_sequence = message.sequence
        if current_epoch is not None and message.world_epoch != current_epoch:
            state = None
            current_version = None
        current_epoch = message.world_epoch
        if message.message_kind is MessageKind.WORLD_SNAPSHOT:
            candidate = message.payload.get("state")
            if not isinstance(candidate, dict):
                errors.append("WORLD_SNAPSHOT missing state object")
                continue
            state = deepcopy(candidate)
            current_version = message.world_version
            expected = gameplay_digest(state)
            actual = message.payload.get("state_digest")
            if actual != expected:
                errors.append(
                    f"{BridgeErrorCode.STATE_DIGEST_MISMATCH.value}: snapshot digest mismatch"
                )
            final_digest_value = expected
        elif message.message_kind is MessageKind.WORLD_DELTA:
            if state is None or current_version is None:
                errors.append("WORLD_DELTA received before a snapshot")
                continue
            from_version = message.payload.get("from_world_version")
            to_version = message.payload.get("to_world_version")
            if from_version != current_version:
                errors.append(
                    f"{BridgeErrorCode.DELTA_SEQUENCE_GAP.value}: expected from version "
                    f"{current_version}, got {from_version}"
                )
                continue
            operations = message.payload.get("operations")
            if not isinstance(operations, list):
                errors.append("WORLD_DELTA operations must be a list")
                continue
            try:
                state = apply_json_operations(state, operations)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f"Failed to apply delta: {exc}")
                continue
            current_version = int(to_version)
            expected = gameplay_digest(state)
            actual = message.payload.get("state_digest_after")
            if actual != expected:
                errors.append(
                    f"{BridgeErrorCode.STATE_DIGEST_MISMATCH.value}: delta digest mismatch"
                )
            final_digest_value = expected
    return ReplayResult(
        passed=not errors,
        message_count=count,
        final_world_version=current_version,
        final_digest=final_digest_value,
        errors=tuple(errors),
    )
