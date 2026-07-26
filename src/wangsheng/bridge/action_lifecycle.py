from __future__ import annotations

from collections import ChainMap, OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import BridgeErrorCode, BridgeProtocolError
from .protocol import content_fingerprint


class ActionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    @property
    def terminal(self) -> bool:
        return self in {
            ActionStatus.REJECTED,
            ActionStatus.COMPLETED,
            ActionStatus.FAILED,
            ActionStatus.CANCELLED,
            ActionStatus.EXPIRED,
        }


_ALLOWED: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.REQUESTED: frozenset({ActionStatus.REJECTED, ActionStatus.ACCEPTED}),
    ActionStatus.ACCEPTED: frozenset({ActionStatus.STARTED, ActionStatus.CANCELLED}),
    ActionStatus.STARTED: frozenset(
        {
            ActionStatus.COMPLETED,
            ActionStatus.FAILED,
            ActionStatus.CANCELLED,
            ActionStatus.EXPIRED,
        }
    ),
    ActionStatus.REJECTED: frozenset(),
    ActionStatus.COMPLETED: frozenset(),
    ActionStatus.FAILED: frozenset(),
    ActionStatus.CANCELLED: frozenset(),
    ActionStatus.EXPIRED: frozenset(),
}


@dataclass(slots=True)
class ActionRecord:
    action_id: str
    actor_id: str
    action_name: str
    arguments: dict[str, Any]
    based_on_world_epoch: str
    based_on_world_version: int
    deadline_virtual_time_ms: int | None
    task_generation: int
    task_id: str | None = None
    tick_id: str | None = None
    status: ActionStatus = ActionStatus.REQUESTED
    requested_at_ms: int = 0
    accepted_at_ms: int | None = None
    started_at_ms: int | None = None
    terminal_at_ms: int | None = None
    completion_due_ms: int | None = None
    terminal_code: str | None = None
    terminal_payload: dict[str, Any] = field(default_factory=dict)

    def request_fingerprint(self) -> str:
        return content_fingerprint(
            {
                "action_id": self.action_id,
                "actor_id": self.actor_id,
                "action_name": self.action_name,
                "arguments": self.arguments,
                "based_on_world_epoch": self.based_on_world_epoch,
                "based_on_world_version": self.based_on_world_version,
                "deadline_virtual_time_ms": self.deadline_virtual_time_ms,
                "task_generation": self.task_generation,
                "task_id": self.task_id,
                "tick_id": self.tick_id,
            }
        )

    def to_dict(self, *, now_ms: int | None = None) -> dict[str, Any]:
        remaining = None
        if now_ms is not None and self.status is ActionStatus.STARTED and self.completion_due_ms is not None:
            remaining = max(0, self.completion_due_ms - now_ms)
        return {
            "action_id": self.action_id,
            "actor_id": self.actor_id,
            "action_name": self.action_name,
            "arguments": dict(self.arguments),
            "based_on_world_epoch": self.based_on_world_epoch,
            "based_on_world_version": self.based_on_world_version,
            "deadline_virtual_time_ms": self.deadline_virtual_time_ms,
            "task_generation": self.task_generation,
            "task_id": self.task_id,
            "tick_id": self.tick_id,
            "status": self.status.value,
            "requested_at_ms": self.requested_at_ms,
            "accepted_at_ms": self.accepted_at_ms,
            "started_at_ms": self.started_at_ms,
            "terminal_at_ms": self.terminal_at_ms,
            "completion_due_ms": self.completion_due_ms,
            "remaining_duration_ms": remaining,
            "terminal_code": self.terminal_code,
            "terminal_payload": dict(self.terminal_payload),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionRecord":
        return cls(
            action_id=payload["action_id"],
            actor_id=payload["actor_id"],
            action_name=payload["action_name"],
            arguments=dict(payload.get("arguments", {})),
            based_on_world_epoch=payload["based_on_world_epoch"],
            based_on_world_version=int(payload["based_on_world_version"]),
            deadline_virtual_time_ms=payload.get("deadline_virtual_time_ms"),
            task_generation=int(payload["task_generation"]),
            task_id=payload.get("task_id"),
            tick_id=payload.get("tick_id"),
            status=ActionStatus(payload["status"]),
            requested_at_ms=int(payload.get("requested_at_ms", 0)),
            accepted_at_ms=payload.get("accepted_at_ms"),
            started_at_ms=payload.get("started_at_ms"),
            terminal_at_ms=payload.get("terminal_at_ms"),
            completion_due_ms=payload.get("completion_due_ms"),
            terminal_code=payload.get("terminal_code"),
            terminal_payload=dict(payload.get("terminal_payload", {})),
        )


@dataclass(slots=True)
class ActionLedger:
    """Bounded live action state with a deterministic terminal idempotency window.

    ``active_records`` contains only non-terminal actions. Completed, failed,
    cancelled, expired, and rejected actions are moved into ``terminal_records``.
    The terminal cache is FIFO-bounded so the authoritative live world cannot
    retain an unbounded action history; the JSONL bridge trace remains the
    permanent audit history.
    """

    active_records: dict[str, ActionRecord] = field(default_factory=dict)
    terminal_records: OrderedDict[str, ActionRecord] = field(default_factory=OrderedDict)
    terminal_cache_limit: int = 256

    def __post_init__(self) -> None:
        if self.terminal_cache_limit <= 0:
            raise ValueError("terminal_cache_limit must be positive")
        if not isinstance(self.terminal_records, OrderedDict):
            self.terminal_records = OrderedDict(self.terminal_records)
        self._prune_terminal_cache()

    @property
    def records(self) -> Mapping[str, ActionRecord]:
        """Compatibility read view over active plus retained terminal actions."""
        return ChainMap(self.active_records, self.terminal_records)

    def get(self, action_id: str) -> ActionRecord | None:
        record = self.active_records.get(action_id)
        if record is not None:
            return record
        return self.terminal_records.get(action_id)

    def register(self, record: ActionRecord) -> tuple[ActionRecord, bool]:
        existing = self.get(record.action_id)
        if existing is None:
            if record.status.terminal:
                self._remember_terminal(record)
            else:
                self.active_records[record.action_id] = record
            return record, True
        if existing.request_fingerprint() != record.request_fingerprint():
            raise BridgeProtocolError(
                BridgeErrorCode.DUPLICATE_ACTION_CONFLICT,
                f"Action ID {record.action_id!r} was reused with different content.",
            )
        return existing, False

    def transition(
        self,
        action_id: str,
        target: ActionStatus,
        *,
        now_ms: int,
        code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ActionRecord:
        record = self.get(action_id)
        if record is None:
            raise KeyError(action_id)
        if record.status is target:
            return record
        if record.status.terminal:
            return record
        if target not in _ALLOWED[record.status]:
            raise BridgeProtocolError(
                BridgeErrorCode.INTERNAL_BRIDGE_ERROR,
                f"Invalid action lifecycle transition {record.status.value}->{target.value}.",
                {"action_id": action_id},
            )
        record.status = target
        if target is ActionStatus.ACCEPTED:
            record.accepted_at_ms = now_ms
        elif target is ActionStatus.STARTED:
            record.started_at_ms = now_ms
        elif target.terminal:
            record.terminal_at_ms = now_ms
            record.terminal_code = code
            record.terminal_payload = dict(payload or {})
            self.active_records.pop(action_id, None)
            self._remember_terminal(record)
        return record

    def active_for_actor(self, actor_id: str) -> ActionRecord | None:
        active = [
            record
            for record in self.active_records.values()
            if record.actor_id == actor_id
            and record.status in {ActionStatus.ACCEPTED, ActionStatus.STARTED}
        ]
        if len(active) > 1:
            raise BridgeProtocolError(
                BridgeErrorCode.INTERNAL_BRIDGE_ERROR,
                f"Actor {actor_id!r} has multiple active actions.",
            )
        return active[0] if active else None

    def active_to_dict(self, *, now_ms: int) -> dict[str, Any]:
        return {
            action_id: record.to_dict(now_ms=now_ms)
            for action_id, record in sorted(self.active_records.items())
        }

    def terminal_cache_to_list(self, *, now_ms: int) -> list[dict[str, Any]]:
        return [record.to_dict(now_ms=now_ms) for record in self.terminal_records.values()]

    def to_dict(self, *, now_ms: int) -> dict[str, Any]:
        """Legacy merged serialization retained for diagnostics only."""
        return {
            action_id: record.to_dict(now_ms=now_ms)
            for action_id, record in sorted(self.records.items())
        }

    def _remember_terminal(self, record: ActionRecord) -> None:
        self.terminal_records[record.action_id] = record
        self.terminal_records.move_to_end(record.action_id)
        self._prune_terminal_cache()

    def _prune_terminal_cache(self) -> None:
        while len(self.terminal_records) > self.terminal_cache_limit:
            self.terminal_records.popitem(last=False)

    @classmethod
    def from_state(
        cls,
        *,
        active_payload: dict[str, Any] | None,
        terminal_payload: list[dict[str, Any]] | dict[str, Any] | None,
        terminal_cache_limit: int = 256,
    ) -> "ActionLedger":
        ledger = cls(terminal_cache_limit=terminal_cache_limit)
        for action_id, payload in (active_payload or {}).items():
            record = ActionRecord.from_dict(payload)
            if record.action_id != action_id:
                raise ValueError("active action key does not match record action_id")
            if record.status.terminal:
                ledger._remember_terminal(record)
            else:
                ledger.active_records[action_id] = record

        if isinstance(terminal_payload, dict):
            # Backward-compatible order for pre-fix snapshots.
            terminal_items = [
                ActionRecord.from_dict(payload)
                for _, payload in sorted(terminal_payload.items())
            ]
            terminal_items.sort(
                key=lambda item: (
                    item.terminal_at_ms if item.terminal_at_ms is not None else -1,
                    item.action_id,
                )
            )
        else:
            terminal_items = [
                ActionRecord.from_dict(payload)
                for payload in (terminal_payload or [])
            ]
        for record in terminal_items:
            if not record.status.terminal:
                raise ValueError("terminal action cache contains a non-terminal record")
            ledger._remember_terminal(record)
        return ledger

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionLedger":
        """Backward-compatible loader for the old merged action dictionary."""
        return cls.from_state(
            active_payload=payload,
            terminal_payload=None,
        )
