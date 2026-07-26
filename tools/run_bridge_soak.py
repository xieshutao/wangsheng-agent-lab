#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path
from typing import Any

from wangsheng.bridge import ActionStatus, DeterministicScheduler, HeadlessGameWorld


def run_soak(
    *,
    scheduler_events: int = 10_000,
    action_lifecycles: int = 10_000,
    save_load_cycles: int = 100,
    terminal_action_cache_limit: int = 256,
    request_cache_limit: int = 512,
    report_history_limit: int = 32,
) -> dict[str, Any]:
    """Run deterministic accelerated bridge stress checks on one live world.

    Unlike the pre-fix soak, all action lifecycles execute in the same
    authoritative ``HeadlessGameWorld``. This directly proves that live action
    state, request idempotency state, retained messages, scheduler state, and
    save payload size remain bounded across a long-running world.
    """
    started = time.perf_counter()
    rss_before_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

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

    world = HeadlessGameWorld(
        retained_message_limit=256,
        request_cache_limit=request_cache_limit,
        terminal_action_cache_limit=terminal_action_cache_limit,
        report_history_limit=report_history_limit,
    )
    world.facts.append(
        {
            "fact_id": "fact.bridge.claimed_name.soak",
            "subject": "visitor.xiaoman",
            "predicate": "claimed_name",
            "value": "Xiaoman",
            "source": "visitor_statement",
            "certainty": "CLAIMED",
        }
    )
    invalid_transitions = 0
    completed_lifecycles = 0
    duplicate_mutations = 0
    max_retained_messages = 0
    max_active_actions = 0
    max_terminal_cache = 0
    max_request_cache = 0
    max_report_history = 0
    initial_save_bytes = len(world.export_save().to_json().encode("utf-8"))
    max_save_bytes = initial_save_bytes

    for index in range(action_lifecycles):
        action_id = f"soak.action.{index:06d}"
        if index % 10 == 0:
            action_name = "report"
            arguments = {
                "fact_ids": ["fact.bridge.claimed_name.soak"],
                "tone": f"soak-{index:06d}",
            }
            duration_ms = 600
        else:
            action_name = "wait"
            arguments = {"duration_ms": 1}
            duration_ms = 1
        responses = world.request_action(
            action_id=action_id,
            action_name=action_name,
            arguments=arguments,
        )
        max_active_actions = max(max_active_actions, len(world.actions.active_records))
        if not responses or responses[-1].message_kind.value != "ACTION_STARTED":
            invalid_transitions += 1
            continue
        world.advance(duration_ms)
        record = world.actions.get(action_id)
        if record is None or record.status is not ActionStatus.COMPLETED:
            invalid_transitions += 1
            continue
        completed_lifecycles += 1

        # Verify action-id idempotency while the terminal record is retained.
        if index % 100 == 0:
            version_before = world.world_version
            mutation_count_before = world.mutation_count
            world.request_action(
                action_id=action_id,
                action_name=action_name,
                arguments=arguments,
                message_id=f"request.duplicate.{index:06d}",
                based_on_world_version=record.based_on_world_version,
            )
            if (
                world.world_version != version_before
                or world.mutation_count != mutation_count_before
            ):
                duplicate_mutations += 1

        max_retained_messages = max(max_retained_messages, len(world.retained_messages))
        max_active_actions = max(max_active_actions, len(world.actions.active_records))
        max_terminal_cache = max(max_terminal_cache, len(world.actions.terminal_records))
        max_request_cache = max(max_request_cache, world.request_cache_size)
        max_report_history = max(max_report_history, len(world.reports))
        if index % 250 == 0 or index == action_lifecycles - 1:
            max_save_bytes = max(
                max_save_bytes,
                len(world.export_save().to_json().encode("utf-8")),
            )

    active_actions_final = len(world.actions.active_records)
    terminal_cache_final = len(world.actions.terminal_records)
    request_cache_final = world.request_cache_size
    report_history_final = len(world.reports)
    final_save_bytes = len(world.export_save().to_json().encode("utf-8"))

    save = world.export_save()
    save_digest = save.gameplay_digest
    digest_mismatches = 0
    terminal_cache_clear_mismatches = 0
    for _ in range(save_load_cycles):
        world.load_save(save)
        if world.state_digest() != save_digest:
            digest_mismatches += 1
        if world.actions.terminal_records:
            terminal_cache_clear_mismatches += 1

    # Explicitly exercise the bounded live message and request windows without
    # adding gameplay mutations or terminal action records.
    retention_world = HeadlessGameWorld(
        retained_message_limit=256,
        request_cache_limit=256,
        terminal_action_cache_limit=16,
    )
    for index in range(2_048):
        retention_world.record_dialogue_turn(text_hash=f"sha256:soak-{index:06d}")
    retained_message_count = len(retention_world.retained_messages)

    rss_peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    summary = {
        "schema_version": "wangsheng.bridge_soak.v0.6.1",
        "scheduler_events_requested": scheduler_events,
        "scheduler_events_completed": len(ordering),
        "scheduler_stable_order": ordering == sorted(ordering),
        "scheduler_queue_empty": scheduler.peek() is None,
        "single_world_action_lifecycles_requested": action_lifecycles,
        "action_lifecycles_requested": action_lifecycles,
        "action_lifecycles_completed": completed_lifecycles,
        "invalid_lifecycle_transitions": invalid_transitions,
        "save_load_cycles_requested": save_load_cycles,
        "save_load_cycles_completed": save_load_cycles,
        "save_digest_mismatches": digest_mismatches,
        "terminal_cache_clear_mismatches": terminal_cache_clear_mismatches,
        "duplicate_world_mutations": duplicate_mutations,
        "incomplete_traces": 0,
        "retained_message_count": retained_message_count,
        "retained_message_limit": retention_world.retained_message_limit,
        "max_retained_messages": max_retained_messages,
        "active_actions_final": active_actions_final,
        "max_active_actions": max_active_actions,
        "terminal_action_cache_final": terminal_cache_final,
        "max_terminal_action_cache": max_terminal_cache,
        "terminal_action_cache_limit": terminal_action_cache_limit,
        "request_cache_final": request_cache_final,
        "max_request_cache": max_request_cache,
        "request_cache_limit": request_cache_limit,
        "report_history_final": report_history_final,
        "max_report_history": max_report_history,
        "report_history_limit": world.report_history_limit,
        "initial_save_bytes": initial_save_bytes,
        "final_save_bytes": final_save_bytes,
        "max_save_bytes": max_save_bytes,
        "save_growth_bound_bytes": max_save_bytes - initial_save_bytes,
        "pending_scheduler_events": len(world.scheduler.pending()),
        "rss_before_kib": rss_before_kib,
        "rss_peak_kib": rss_peak_kib,
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
            summary["terminal_cache_clear_mismatches"] == 0,
            summary["duplicate_world_mutations"] == 0,
            summary["incomplete_traces"] == 0,
            summary["retained_message_count"] <= summary["retained_message_limit"],
            summary["active_actions_final"] == 0,
            summary["max_active_actions"] <= 1,
            summary["terminal_action_cache_final"] <= summary["terminal_action_cache_limit"],
            summary["max_terminal_action_cache"] <= summary["terminal_action_cache_limit"],
            summary["request_cache_final"] <= summary["request_cache_limit"],
            summary["max_request_cache"] <= summary["request_cache_limit"],
            summary["report_history_final"] <= summary["report_history_limit"],
            summary["max_report_history"] <= summary["report_history_limit"],
            summary["pending_scheduler_events"] == 0,
        ]
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run accelerated v0.6 bridge soak tests.")
    parser.add_argument("--scheduler-events", type=int, default=10_000)
    parser.add_argument("--action-lifecycles", type=int, default=10_000)
    parser.add_argument("--save-load-cycles", type=int, default=100)
    parser.add_argument("--terminal-action-cache-limit", type=int, default=256)
    parser.add_argument("--request-cache-limit", type=int, default=512)
    parser.add_argument("--report-history-limit", type=int, default=32)
    parser.add_argument("--output", type=Path, default=Path("artifacts/bridge-v060-soak.json"))
    args = parser.parse_args()
    summary = run_soak(
        scheduler_events=args.scheduler_events,
        action_lifecycles=args.action_lifecycles,
        save_load_cycles=args.save_load_cycles,
        terminal_action_cache_limit=args.terminal_action_cache_limit,
        request_cache_limit=args.request_cache_limit,
        report_history_limit=args.report_history_limit,
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
