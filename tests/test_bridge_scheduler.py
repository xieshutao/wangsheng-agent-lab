from __future__ import annotations

from wangsheng.bridge.scheduler import DeterministicScheduler


def test_scheduler_orders_by_time_priority_and_insertion() -> None:
    scheduler = DeterministicScheduler()
    scheduler.schedule_at(event_id="late", event_kind="x", scheduled_time_ms=10, priority=1)
    scheduler.schedule_at(event_id="same-b", event_kind="x", scheduled_time_ms=5, priority=2)
    scheduler.schedule_at(event_id="same-a", event_kind="x", scheduled_time_ms=5, priority=1)
    scheduler.schedule_at(event_id="same-a2", event_kind="x", scheduled_time_ms=5, priority=1)
    assert [scheduler.pop_next().event_id for _ in range(4)] == [  # type: ignore[union-attr]
        "same-a",
        "same-a2",
        "same-b",
        "late",
    ]


def test_scheduler_cancel_removes_event() -> None:
    scheduler = DeterministicScheduler()
    scheduler.schedule_after(event_id="cancel", event_kind="x", delay_ms=10)
    assert scheduler.cancel("cancel")
    assert scheduler.peek() is None


def test_scheduler_snapshot_round_trip() -> None:
    scheduler = DeterministicScheduler(now_ms=7)
    scheduler.schedule_after(event_id="one", event_kind="x", delay_ms=3, payload={"a": 1})
    restored = DeterministicScheduler.from_snapshot(scheduler.snapshot())
    assert restored.snapshot() == scheduler.snapshot()
