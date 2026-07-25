from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from time import time
from typing import Any

from .models import ActiveTask, Observation, PolicyContext, WorldState


TRACE_REQUIRED_FIELDS = frozenset({
    "schema_version", "episode_id", "event_type", "sequence", "timestamp",
})
TICK_REQUIRED_FIELDS = TRACE_REQUIRED_FIELDS | frozenset({
    "step", "task_id", "context_hash", "action", "gateway", "executor",
    "observation", "world_before", "world_after", "state_delta", "task_status",
})


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def state_delta(before: Any, after: Any, prefix: str = "") -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in before:
                changes[path] = {"from": None, "to": after[key]}
            elif key not in after:
                changes[path] = {"from": before[key], "to": None}
            else:
                changes.update(state_delta(before[key], after[key], path))
    elif before != after:
        changes[prefix] = {"from": before, "to": after}
    return changes


@dataclass(slots=True)
class JsonlTraceRecorder:
    path: Path
    episode_id: str
    schema_version: str = "wangsheng.trace.v1"
    records: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def record_tick(
        self,
        *,
        step: int,
        context: PolicyContext,
        observation: Observation,
        world_before: dict[str, Any],
        world_after: dict[str, Any],
        gateway_status: str,
        duration_ms: float,
        task: ActiveTask,
    ) -> dict[str, Any]:
        executor_status = "not_run" if observation.source != "executor" else ("success" if observation.success else "failure")
        record = {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "event_type": "tick",
            "sequence": len(self.records),
            "timestamp": time(),
            "step": step,
            "task_id": task.spec.task_id,
            "context_hash": stable_hash({
                "command": context.command,
                "world": context.world,
                "observations": context.observations,
                "tools": context.tool_schemas,
            }),
            "context": {
                "command": context.command,
                "available_actions": list(context.available_actions),
                "forbidden_actions": list(context.forbidden_actions),
                "world": context.world,
                "previous_observations": list(context.observations),
            },
            "action": observation.action.to_dict(),
            "gateway": {
                "status": gateway_status,
                "reason_code": observation.code if observation.source == "gateway" else "NONE",
            },
            "executor": {
                "status": executor_status,
                "reason_code": observation.code if observation.source == "executor" else "NONE",
            },
            "observation": observation.to_dict(),
            "world_before": world_before,
            "world_after": world_after,
            "state_delta": state_delta(world_before, world_after),
            "memory_events": [],
            "task_status": task.status.value,
            "terminal_reason": task.terminal_reason,
            "duration_ms": round(duration_ms, 3),
        }
        self._append(record)
        return record

    def record_external_event(self, *, name: str, details: dict[str, Any], world: WorldState, task: ActiveTask) -> None:
        self._append({
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "event_type": "external_event",
            "sequence": len(self.records),
            "timestamp": time(),
            "name": name,
            "details": details,
            "world": world.snapshot(),
            "task_status": task.status.value,
        })

    def _append(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def validate(self) -> list[str]:
        errors: list[str] = []
        for index, record in enumerate(self.records):
            required = TICK_REQUIRED_FIELDS if record.get("event_type") == "tick" else TRACE_REQUIRED_FIELDS
            missing = sorted(required - set(record))
            if missing:
                errors.append(f"record {index} missing {missing}")
        return errors


def write_episode_summary(path: str | Path, *, task: ActiveTask, world: WorldState, trace_path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": {
            "task_id": task.spec.task_id,
            "command": task.spec.command,
            "status": task.status.value,
            "step_count": task.step_count,
            "terminal_reason": task.terminal_reason,
        },
        "world": world.snapshot(),
        "observations": [observation.to_dict() for observation in task.observations],
        "trace_path": str(trace_path),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def write_trace(path: str | Path, *, task: ActiveTask, world: WorldState) -> Path:
    return write_episode_summary(path, task=task, world=world, trace_path="")
