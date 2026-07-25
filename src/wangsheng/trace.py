from __future__ import annotations
import json
from pathlib import Path
from .models import ActiveTask, WorldState

def write_trace(path: str | Path, *, task: ActiveTask, world: WorldState) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"task": {"task_id": task.spec.task_id, "command": task.spec.command,
                        "status": task.status.value, "step_count": task.step_count,
                        "terminal_reason": task.terminal_reason},
               "world": world.snapshot(),
               "observations": [o.to_dict() for o in task.observations]}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
