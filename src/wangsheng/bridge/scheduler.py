from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any


@dataclass(order=True, slots=True)
class ScheduledEvent:
    scheduled_time_ms: int
    priority: int
    insertion_sequence: int
    event_id: str = field(compare=False)
    event_kind: str = field(compare=False)
    payload: dict[str, Any] = field(default_factory=dict, compare=False)
    cancelled: bool = field(default=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduled_time_ms": self.scheduled_time_ms,
            "priority": self.priority,
            "insertion_sequence": self.insertion_sequence,
            "event_id": self.event_id,
            "event_kind": self.event_kind,
            "payload": dict(self.payload),
            "cancelled": self.cancelled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScheduledEvent":
        return cls(
            int(payload["scheduled_time_ms"]),
            int(payload["priority"]),
            int(payload["insertion_sequence"]),
            str(payload["event_id"]),
            str(payload["event_kind"]),
            dict(payload.get("payload", {})),
            bool(payload.get("cancelled", False)),
        )


@dataclass(slots=True)
class DeterministicScheduler:
    now_ms: int = 0
    next_insertion_sequence: int = 1
    _heap: list[ScheduledEvent] = field(default_factory=list)
    _events: dict[str, ScheduledEvent] = field(default_factory=dict)

    def schedule_at(
        self,
        *,
        event_id: str,
        event_kind: str,
        scheduled_time_ms: int,
        priority: int = 100,
        payload: dict[str, Any] | None = None,
    ) -> ScheduledEvent:
        if scheduled_time_ms < self.now_ms:
            raise ValueError("Cannot schedule an event in the past.")
        if event_id in self._events:
            existing = self._events[event_id]
            candidate = ScheduledEvent(
                scheduled_time_ms,
                priority,
                existing.insertion_sequence,
                event_id,
                event_kind,
                dict(payload or {}),
            )
            if existing.to_dict() != candidate.to_dict():
                raise ValueError(f"Event ID {event_id!r} already exists with different content.")
            return existing
        event = ScheduledEvent(
            scheduled_time_ms,
            priority,
            self.next_insertion_sequence,
            event_id,
            event_kind,
            dict(payload or {}),
        )
        self.next_insertion_sequence += 1
        self._events[event_id] = event
        heapq.heappush(self._heap, event)
        return event

    def schedule_after(
        self,
        *,
        event_id: str,
        event_kind: str,
        delay_ms: int,
        priority: int = 100,
        payload: dict[str, Any] | None = None,
    ) -> ScheduledEvent:
        if delay_ms < 0:
            raise ValueError("delay_ms must be non-negative.")
        return self.schedule_at(
            event_id=event_id,
            event_kind=event_kind,
            scheduled_time_ms=self.now_ms + delay_ms,
            priority=priority,
            payload=payload,
        )

    def cancel(self, event_id: str) -> bool:
        event = self._events.get(event_id)
        if event is None or event.cancelled:
            return False
        event.cancelled = True
        return True

    def peek(self) -> ScheduledEvent | None:
        self._discard_cancelled()
        return self._heap[0] if self._heap else None

    def pop_next(self) -> ScheduledEvent | None:
        self._discard_cancelled()
        if not self._heap:
            return None
        event = heapq.heappop(self._heap)
        self._events.pop(event.event_id, None)
        self.now_ms = event.scheduled_time_ms
        return event

    def set_now(self, value: int) -> None:
        if value < self.now_ms:
            raise ValueError("Virtual time cannot move backwards.")
        self.now_ms = value

    def _discard_cancelled(self) -> None:
        while self._heap and self._heap[0].cancelled:
            event = heapq.heappop(self._heap)
            self._events.pop(event.event_id, None)

    def pending(self) -> list[ScheduledEvent]:
        return sorted(event for event in self._events.values() if not event.cancelled)

    def snapshot(self) -> dict[str, Any]:
        return {
            "now_ms": self.now_ms,
            "next_insertion_sequence": self.next_insertion_sequence,
            "events": [event.to_dict() for event in self.pending()],
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "DeterministicScheduler":
        scheduler = cls(
            now_ms=int(payload.get("now_ms", 0)),
            next_insertion_sequence=int(payload.get("next_insertion_sequence", 1)),
        )
        for event_payload in payload.get("events", []):
            event = ScheduledEvent.from_dict(event_payload)
            scheduler._events[event.event_id] = event
            heapq.heappush(scheduler._heap, event)
        return scheduler
