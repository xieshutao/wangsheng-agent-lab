from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .action_lifecycle import ActionStatus
from .errors import BridgeErrorCode, BridgeProtocolError
from .headless_world import HeadlessGameWorld
from .messages import MessageKind
from .protocol import gameplay_digest
from .savegame import SaveGame
from .scheduler import DeterministicScheduler
from .transport import replay_message_stream


@dataclass(frozen=True, slots=True)
class BridgeScenario:
    scenario_id: str
    kind: str
    description: str

    @classmethod
    def from_path(cls, path: Path) -> "BridgeScenario":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "wangsheng.bridge_scenario.v0.6":
            raise ValueError(f"Unsupported bridge scenario schema in {path}.")
        return cls(payload["scenario_id"], payload["kind"], payload["description"])


@dataclass(frozen=True, slots=True)
class BridgeScenarioResult:
    scenario_id: str
    passed: bool
    checks: dict[str, bool]
    metrics: dict[str, Any]
    errors: tuple[str, ...]
    trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "wangsheng.bridge_scenario_result.v0.6",
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "checks": dict(self.checks),
            "metrics": dict(self.metrics),
            "errors": list(self.errors),
            "trace": list(self.trace),
        }


def discover_bridge_scenarios(directory: str | Path) -> list[BridgeScenario]:
    return [BridgeScenario.from_path(path) for path in sorted(Path(directory).glob("*.json"))]


def _run_normal_lifecycle() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.emit_snapshot()
    world.request_action(action_id="a.move.door", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(1000)
    world.request_action(action_id="a.ask", action_name="ask_through", arguments={"topic": "identity"})
    world.advance(1200)
    world.request_action(action_id="a.move.player", action_name="move_to", arguments={"target_id": "player"})
    world.advance(1000)
    fact_id = world.facts[0]["fact_id"]
    world.request_action(action_id="a.report", action_name="report", arguments={"fact_ids": [fact_id], "tone": "neutral"})
    world.advance(600)
    checks = {
        "all_actions_completed": all(record.status is ActionStatus.COMPLETED for record in world.actions.records.values()),
        "fact_acquired": len(world.facts) == 1 and world.facts[0]["predicate"] == "claimed_name",
        "report_recorded": len(world.reports) == 1,
        "door_remained_closed": not world.door["open"],
        "npc_returned_to_player": world.entities["npc.qingyan"]["location"] == world.entities["player"]["location"],
    }
    return checks, {"action_count": len(world.actions.records)}, [], world


def _run_duplicate_action_request() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    request = world.make_message(
        MessageKind.ACTION_REQUESTED,
        message_id="request.duplicate",
        action_id="a.duplicate",
        task_id=world.active_task_id,
        payload={
            "actor_id": "npc.qingyan",
            "action_name": "move_to",
            "arguments": {"target_id": "door.front"},
            "based_on_world_epoch": world.world_epoch,
            "based_on_world_version": world.world_version,
            "deadline_virtual_time_ms": None,
            "task_generation": world.task_generation,
        },
    )
    first = world.handle(request)
    version_after_first = world.world_version
    mutations_after_first = world.mutation_count
    second = world.handle(request)
    checks = {
        "responses_cached": [item.message_id for item in first] == [item.message_id for item in second],
        "version_unchanged": world.world_version == version_after_first,
        "mutation_count_unchanged": world.mutation_count == mutations_after_first,
        "single_action_record": len(world.actions.records) == 1,
    }
    return checks, {"response_count": len(first)}, [], world


def _run_duplicate_completion_callback() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(action_id="a.callback", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(1000)
    version = world.world_version
    mutations = world.mutation_count
    location = world.entities["npc.qingyan"]["location"]
    emitted = world.simulate_completion_callback("a.callback")
    checks = {
        "no_new_messages": emitted == (),
        "version_unchanged": world.world_version == version,
        "mutation_unchanged": world.mutation_count == mutations,
        "location_unchanged": world.entities["npc.qingyan"]["location"] == location,
    }
    return checks, {}, [], world


def _run_stale_world_version() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.apply_world_event("door_locked", {"locked": True})
    before = world.state_digest()
    responses = world.request_action(
        action_id="a.stale.version",
        action_name="observe",
        arguments={"target_id": "door.front"},
        based_on_world_version=0,
    )
    checks = {
        "rejected": responses[-1].message_kind is MessageKind.ACTION_REJECTED,
        "correct_code": responses[-1].payload.get("error_code") == BridgeErrorCode.STALE_WORLD_VERSION.value,
        "state_effect_free": world.state_digest() == before,
        "no_physical_change": world.door["locked"] is True,
    }
    return checks, {}, [], world


def _run_stale_epoch_after_load() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    old_epoch = world.world_epoch
    old_version = world.world_version
    pending = world.make_message(
        MessageKind.ACTION_REQUESTED,
        message_id="request.old.epoch",
        action_id="a.old.epoch",
        task_id=world.active_task_id,
        payload={
            "actor_id": "npc.qingyan",
            "action_name": "move_to",
            "arguments": {"target_id": "door.front"},
            "based_on_world_epoch": old_epoch,
            "based_on_world_version": old_version,
            "deadline_virtual_time_ms": None,
            "task_generation": world.task_generation,
        },
    )
    save = world.export_save()
    world.load_save(save)
    responses = world.handle(pending)
    checks = {
        "epoch_changed": world.world_epoch != old_epoch,
        "stale_rejected": responses[-1].payload.get("error_code") == BridgeErrorCode.STALE_WORLD_EPOCH.value,
        "actor_not_moved": world.entities["npc.qingyan"]["location"] == "anchor.player",
    }
    return checks, {}, [], world


def _run_cancel_during_movement() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(action_id="a.cancel", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(400)
    world.cancel_task(reason="player_cancelled")
    world.advance(2000)
    record = world.actions.records["a.cancel"]
    checks = {
        "cancelled_once": record.status is ActionStatus.CANCELLED,
        "no_late_effect": world.entities["npc.qingyan"]["location"] == "anchor.player",
        "task_generation_advanced": world.task_generation == 2,
    }
    return checks, {}, [], world


def _run_pause_freezes_progress() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(action_id="a.pause", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(400)
    world.pause()
    paused_time = world.virtual_time_ms
    world.advance(5000)
    still_started = world.actions.records["a.pause"].status is ActionStatus.STARTED
    world.resume()
    world.advance(600)
    checks = {
        "clock_frozen": paused_time == 400,
        "active_while_paused": still_started,
        "completed_after_resume": world.actions.records["a.pause"].status is ActionStatus.COMPLETED,
        "arrived": world.entities["npc.qingyan"]["location"] == "anchor.door",
    }
    return checks, {}, [], world


def _run_resume_requires_fresh_decision() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.pause()
    rejected = world.request_action(action_id="a.paused", action_name="move_to", arguments={"target_id": "door.front"})[-1]
    world.resume()
    world.advance(2000)
    fresh = world.request_action(action_id="a.fresh", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(1000)
    checks = {
        "paused_request_rejected": rejected.payload.get("error_code") == BridgeErrorCode.GAME_PAUSED.value,
        "rejected_action_not_replayed": "a.paused" not in world.actions.records,
        "fresh_action_required": fresh[-1].message_kind is MessageKind.ACTION_STARTED,
        "fresh_action_completed": world.actions.records["a.fresh"].status is ActionStatus.COMPLETED,
    }
    return checks, {}, [], world


def _run_path_blocked_mid_move() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(action_id="a.blocked", action_name="move_to", arguments={"target_id": "door.front"})
    world.schedule_world_event(event_name="path_reachable", delay_ms=500, payload={"reachable": False})
    world.advance(1000)
    record = world.actions.records["a.blocked"]
    checks = {
        "failed": record.status is ActionStatus.FAILED,
        "correct_code": record.terminal_code == BridgeErrorCode.NO_PATH.value,
        "no_arrival": world.entities["npc.qingyan"]["location"] == "anchor.player",
    }
    return checks, {}, [], world


def _run_visitor_leaves_mid_question() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(action_id="a.to.door", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(1000)
    world.request_action(action_id="a.question", action_name="ask_through", arguments={"topic": "identity"})
    world.schedule_world_event(event_name="visitor_present", delay_ms=500, payload={"present": False})
    world.advance(1200)
    record = world.actions.records["a.question"]
    checks = {
        "failed": record.status is ActionStatus.FAILED,
        "target_gone": record.terminal_code == BridgeErrorCode.TARGET_GONE.value,
        "no_fact": not world.facts,
    }
    return checks, {}, [], world


def _run_action_expires() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(
        action_id="a.expire",
        action_name="wait",
        arguments={"duration_ms": 1000},
        deadline_virtual_time_ms=500,
    )
    world.advance(1000)
    record = world.actions.records["a.expire"]
    checks = {
        "expired": record.status is ActionStatus.EXPIRED,
        "timeout_code": record.terminal_code == BridgeErrorCode.ACTION_TIMEOUT.value,
        "completion_not_applied": record.status is not ActionStatus.COMPLETED,
    }
    return checks, {}, [], world


def _run_save_load_idle() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    save = world.export_save()
    world.apply_world_event("door_locked", {"locked": True})
    world.load_save(save)
    checks = {
        "digest_preserved": world.state_digest() == save.gameplay_digest,
        "door_restored": world.door["locked"] is False,
    }
    return checks, {"save_digest": save.gameplay_digest}, [], world


def _run_save_load_active_action() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(action_id="a.save.active", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(400)
    save = world.export_save()
    world.load_save(save)
    remaining = world.actions.records["a.save.active"].to_dict(now_ms=world.virtual_time_ms)["remaining_duration_ms"]
    world.advance(600)
    checks = {
        "remaining_preserved": remaining == 600,
        "completed_after_load": world.actions.records["a.save.active"].status is ActionStatus.COMPLETED,
        "arrived": world.entities["npc.qingyan"]["location"] == "anchor.door",
    }
    return checks, {}, [], world


def _run_corrupted_save_no_mutation() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    before = world.state_digest()
    payload = world.export_save().to_dict()
    payload["gameplay_state"]["door"]["locked"] = True
    caught = False
    try:
        world.load_save(payload)
    except BridgeProtocolError as exc:
        caught = exc.code is BridgeErrorCode.SAVE_CORRUPTED
    checks = {
        "corruption_rejected": caught,
        "world_unchanged": world.state_digest() == before,
        "door_unchanged": world.door["locked"] is False,
    }
    return checks, {}, [], world


def _run_snapshot_delta_replay() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.emit_snapshot()
    world.request_action(action_id="a.replay", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(1000)
    replay = replay_message_stream(world.retained_messages)
    checks = {
        "replay_passed": replay.passed,
        "digest_match": replay.final_digest == world.state_digest(),
        "version_match": replay.final_world_version == world.world_version,
    }
    return checks, replay.to_dict(), list(replay.errors), world


def _run_delta_gap_detected() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld(retained_message_limit=100)
    world.emit_snapshot()
    world.request_action(action_id="a.gap", action_name="move_to", arguments={"target_id": "door.front"})
    world.advance(1000)
    messages = list(world.retained_messages)
    delta_indexes = [index for index, message in enumerate(messages) if message.message_kind is MessageKind.WORLD_DELTA]
    if delta_indexes:
        messages.pop(delta_indexes[0])
    replay = replay_message_stream(messages)
    checks = {
        "gap_detected": not replay.passed,
        "error_recorded": any("DELTA_SEQUENCE_GAP" in error for error in replay.errors),
    }
    return checks, replay.to_dict(), [], world


def _run_provider_timeout_world_valid() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    before = world.state_digest()
    world.apply_world_event("provider_timeout", {"provider": "local"})
    checks = {
        "digest_unchanged": world.state_digest() == before,
        "world_operational": world.request_action(action_id="a.after.timeout", action_name="wait", arguments={"duration_ms": 0})[-1].message_kind is MessageKind.ACTION_STARTED,
    }
    world.advance(0)
    return checks, {}, [], world


def _run_provider_recovery_no_duplicate() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    world.request_action(action_id="a.recover", action_name="move_to", arguments={"target_id": "door.front"}, message_id="request.recover.1")
    world.apply_world_event("provider_timeout", {"provider": "local"})
    world.advance(1000)
    version = world.world_version
    location = world.entities["npc.qingyan"]["location"]
    duplicate = world.request_action(action_id="a.recover", action_name="move_to", arguments={"target_id": "door.front"}, message_id="request.recover.2", based_on_world_version=0)
    checks = {
        "single_action_record": len(world.actions.records) == 1,
        "terminal_state_returned": duplicate[-1].message_kind is MessageKind.ACTION_COMPLETED,
        "no_new_mutation": world.world_version == version,
        "no_duplicate_effect": world.entities["npc.qingyan"]["location"] == location,
    }
    return checks, {}, [], world


def _run_dialogue_no_world_action() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    world = HeadlessGameWorld()
    before = world.state_digest()
    message = world.record_dialogue_turn(text_hash="sha256:dialogue")
    checks = {
        "tools_empty": message.payload["tools"] == [],
        "tool_choice_none": message.payload["tool_choice"] is None,
        "world_unchanged": world.state_digest() == before,
        "no_actions": not world.actions.records,
    }
    return checks, {}, [], world


def _run_scheduler_10000_events() -> tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]:
    scheduler = DeterministicScheduler()
    for index in range(10_000):
        scheduler.schedule_at(
            event_id=f"event.{index}",
            event_kind="noop",
            scheduled_time_ms=index // 10,
            priority=index % 3,
            payload={"index": index},
        )
    popped = []
    while scheduler.peek() is not None:
        popped.append(scheduler.pop_next())
    keys = [(event.scheduled_time_ms, event.priority, event.insertion_sequence) for event in popped]
    world = HeadlessGameWorld()
    checks = {
        "all_events_processed": len(popped) == 10_000,
        "stable_order": keys == sorted(keys),
        "queue_empty": scheduler.peek() is None,
        "no_world_drift": world.state_digest() == gameplay_digest(world.gameplay_state()),
    }
    return checks, {"processed_events": len(popped)}, [], world


_RUNNERS: dict[str, Callable[[], tuple[dict[str, bool], dict[str, Any], list[str], HeadlessGameWorld]]] = {
    "normal_lifecycle": _run_normal_lifecycle,
    "duplicate_action_request": _run_duplicate_action_request,
    "duplicate_completion_callback": _run_duplicate_completion_callback,
    "stale_world_version": _run_stale_world_version,
    "stale_epoch_after_load": _run_stale_epoch_after_load,
    "cancel_during_movement": _run_cancel_during_movement,
    "pause_freezes_progress": _run_pause_freezes_progress,
    "resume_requires_fresh_decision": _run_resume_requires_fresh_decision,
    "path_blocked_mid_move": _run_path_blocked_mid_move,
    "visitor_leaves_mid_question": _run_visitor_leaves_mid_question,
    "action_expires": _run_action_expires,
    "save_load_idle": _run_save_load_idle,
    "save_load_active_action": _run_save_load_active_action,
    "corrupted_save_no_mutation": _run_corrupted_save_no_mutation,
    "snapshot_delta_replay": _run_snapshot_delta_replay,
    "delta_gap_detected": _run_delta_gap_detected,
    "provider_timeout_world_valid": _run_provider_timeout_world_valid,
    "provider_recovery_no_duplicate": _run_provider_recovery_no_duplicate,
    "dialogue_no_world_action": _run_dialogue_no_world_action,
    "scheduler_10000_events": _run_scheduler_10000_events,
}


def run_bridge_scenario(scenario: BridgeScenario) -> BridgeScenarioResult:
    errors: list[str] = []
    try:
        checks, metrics, runner_errors, world = _RUNNERS[scenario.kind]()
        errors.extend(runner_errors)
    except Exception as exc:  # scenario reports must remain machine-readable
        return BridgeScenarioResult(
            scenario.scenario_id,
            False,
            {},
            {},
            (f"{type(exc).__name__}: {exc}",),
            (),
        )
    passed = bool(checks) and all(checks.values()) and not errors
    return BridgeScenarioResult(
        scenario.scenario_id,
        passed,
        checks,
        metrics,
        tuple(errors),
        tuple(message.to_dict() for message in world.retained_messages),
    )


def run_all_bridge_scenarios(
    scenario_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    scenarios = discover_bridge_scenarios(scenario_dir)
    results = [run_bridge_scenario(scenario) for scenario in scenarios]
    if output_dir is not None:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for result in results:
            (destination / f"{result.scenario_id}.json").write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    summary = {
        "schema_version": "wangsheng.bridge_scenario_summary.v0.6",
        "scenario_count": len(results),
        "passed_count": sum(result.passed for result in results),
        "failed_count": sum(not result.passed for result in results),
        "all_passed": all(result.passed for result in results),
        "results": [result.to_dict() for result in results],
    }
    if output_dir is not None:
        (Path(output_dir) / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return summary
