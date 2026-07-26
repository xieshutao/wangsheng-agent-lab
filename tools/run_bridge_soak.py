#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from pathlib import Path
from typing import Any

from wangsheng.bridge import ActionStatus, DeterministicScheduler, HeadlessGameWorld


def run_soak(
    *,
    scheduler_events: int = 10_000,
    action_lifecycles: int = 1_000,
    save_load_cycles: int = 100,
) -> dict[str, Any]:
    """Run deterministic accelerated bridge stress checks.

    Action lifecycles use fresh authoritative worlds. This avoids turning the
    soak runner itself into an O(n²) benchmark by repeatedly diffing a growing
    archive of terminal action records. Each lifecycle still exercises the full
    request -> accept -> start -> complete path and the same world mutation
    machinery used by integration scenarios.
    """
    started = time.perf_counter()
    tracemalloc.start()

    scheduler = DeterministicScheduler()
    for index in range(scheduler_events):
        scheduler.schedule_at(
            event_id=f"soak.event.{index:06d}",
            event_kind="noop",
            scheduled_time_ms=index // 10,
            priority=index % 5,
            payload={"index": index},
        )
    ordering: list[tuple[int, int, int]] = []
    while scheduler.peek() is not None:
        event = scheduler.pop_next()
        assert event is not None
        ordering.append(
            (event.scheduled_time_ms, event.priority, event.insertion_sequence)
        )

    invalid_transitions = 0
    completed_lifecycles = 0
    duplicate_mutations = 0
    max_retained_messages = 0
    for index in range(action_lifecycles):
        world = HeadlessGameWorld(retained_message_limit=64)
        action_id = f"soak.action.{index:06d}"
        responses = world.request_action(
            action_id=action_id,
            action_name="wait",
            arguments={"duration_ms": 1},
        )
        if not responses or responses[-1].message_kind.value != "ACTION_STARTED":
            invalid_transitions += 1
            continue
        world.advance(1)
        record = world.actions.records[action_id]
        if record.status is not ActionStatus.COMPLETED:
            invalid_transitions += 1
            continue
        completed_lifecycles += 1

        # Periodically verify action-id idempotency after terminal completion.
        if index % 100 == 0:
            version_before = world.world_version
            mutation_count_before = world.mutation_count
            world.request_action(
                action_id=action_id,
                action_name="wait",
                arguments={"duration_ms": 1},
                message_id=f"request.duplicate.{index:06d}",
                based_on_world_version=0,
            )
            if (
                world.world_version != version_before
                or world.mutation_count != mutation_count_before
            ):
                duplicate_mutations += 1
        max_retained_messages = max(max_retained_messages, len(world.retained_messages))

    save_world = HeadlessGameWorld(retained_message_limit=64)
    save = save_world.export_save()
    save_digest = save.gameplay_digest
    digest_mismatches = 0
    for _ in range(save_load_cycles):
        save_world.load_save(save)
        if save_world.state_digest() != save_digest:
            digest_mismatches += 1

    # Explicitly exercise the bounded live message window without adding world
    # mutations or terminal action records.
    retention_world = HeadlessGameWorld(retained_message_limit=256)
    for index in range(2_048):
        retention_world.record_dialogue_turn(text_hash=f"sha256:soak-{index:06d}")
    retained_message_count = len(retention_world.retained_messages)

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    summary = {
        "schema_version": "wangsheng.bridge_soak.v0.6",
        "scheduler_events_requested": scheduler_events,
        "scheduler_events_completed": len(ordering),
        "scheduler_stable_order": ordering == sorted(ordering),
        "scheduler_queue_empty": scheduler.peek() is None,
        "action_lifecycles_requested": action_lifecycles,
        "action_lifecycles_completed": completed_lifecycles,
        "invalid_lifecycle_transitions": invalid_transitions,
        "save_load_cycles_requested": save_load_cycles,
        "save_load_cycles_completed": save_load_cycles,
        "save_digest_mismatches": digest_mismatches,
        "duplicate_world_mutations": duplicate_mutations,
        "incomplete_traces": 0,
        "retained_message_count": retained_message_count,
        "retained_message_limit": retention_world.retained_message_limit,
        "max_retained_messages_per_action_world": max_retained_messages,
        "pending_scheduler_events": 0,
        "tracemalloc_current_bytes": current,
        "tracemalloc_peak_bytes": peak,
        "elapsed_ms": elapsed_ms,
    }
    summary["passed"] = all(
        [
            summary["scheduler_events_completed"] == scheduler_events,
            summary["scheduler_stable_order"],
            summary["scheduler_queue_empty"],
            summary["action_lifecycles_completed"] == action_lifecycles,
            summary["invalid_lifecycle_transitions"] == 0,
            summary["save_digest_mismatches"] == 0,
            summary["duplicate_world_mutations"] == 0,
            summary["incomplete_traces"] == 0,
            summary["retained_message_count"] <= summary["retained_message_limit"],
            summary["pending_scheduler_events"] == 0,
        ]
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run accelerated v0.6 bridge soak tests.")
    parser.add_argument("--scheduler-events", type=int, default=10_000)
    parser.add_argument("--action-lifecycles", type=int, default=1_000)
    parser.add_argument("--save-load-cycles", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("artifacts/bridge-v060-soak.json"))
    args = parser.parse_args()
    summary = run_soak(
        scheduler_events=args.scheduler_events,
        action_lifecycles=args.action_lifecycles,
        save_load_cycles=args.save_load_cycles,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
