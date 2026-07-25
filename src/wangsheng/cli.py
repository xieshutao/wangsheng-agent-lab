from __future__ import annotations
import argparse, json
from .scenarios import make_reference_door_engine, door_visitor_task

def demo_door() -> int:
    engine = make_reference_door_engine()
    task = engine.submit_command(door_visitor_task())
    print(f"Task: {task.spec.command}")
    while not task.is_terminal:
        print(json.dumps(engine.tick().to_dict(), ensure_ascii=False))
    print(json.dumps({"status": task.status.value, "steps": task.step_count,
                      "reason": task.terminal_reason,
                      "door_state": engine.world.objects["front_door"].state},
                     ensure_ascii=False, indent=2))
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(prog="wangsheng")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo-door")
    args = parser.parse_args()
    return demo_door() if args.command == "demo-door" else 2

if __name__ == "__main__": raise SystemExit(main())
