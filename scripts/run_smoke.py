from __future__ import annotations
import json
from pathlib import Path
from wangsheng.scenarios import door_visitor_task, make_reference_door_engine
from wangsheng.trace import write_trace

def main() -> int:
    engine = make_reference_door_engine(); task = engine.submit_command(door_visitor_task()); engine.run_until_terminal()
    path = write_trace(Path("artifacts/review/door_visitor_trace.json"), task=task, world=engine.world)
    print(json.dumps({"status": task.status.value, "steps": task.step_count,
                      "reason": task.terminal_reason, "trace": str(path)}, indent=2))
    return 0

if __name__ == "__main__": raise SystemExit(main())
