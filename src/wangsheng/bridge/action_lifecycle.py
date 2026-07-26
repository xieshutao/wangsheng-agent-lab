from __future__ import annotations

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
    records: dict[str, ActionRecord] = field(default_factory=dict)

    def register(self, record: ActionRecord) -> tuple[ActionRecord, bool]:
        existing = self.records.get(record.action_id)
        if existing is None:
            self.records[record.action_id] = record
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
        record = self.records[action_id]
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
        return record

    def active_for_actor(self, actor_id: str) -> ActionRecord | None:
        active = [
            record
            for record in self.records.values()
            if record.actor_id == actor_id
            and record.status in {ActionStatus.ACCEPTED, ActionStatus.STARTED}
        ]
        if len(active) > 1:
            raise BridgeProtocolError(
                BridgeErrorCode.INTERNAL_BRIDGE_ERROR,
                f"Actor {actor_id!r} has multiple active actions.",
            )
        return active[0] if active else None

    def to_dict(self, *, now_ms: int) -> dict[str, Any]:
        return {
            action_id: record.to_dict(now_ms=now_ms)
            for action_id, record in sorted(self.records.items())
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionLedger":
        return cls(
            {
                action_id: ActionRecord.from_dict(record)
                for action_id, record in payload.items()
            }
        )
