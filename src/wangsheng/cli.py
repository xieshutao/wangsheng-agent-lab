from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import EpisodeEngine
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .policy import ModelPolicy
from .providers import ScriptedTextProvider
from .scenario_runner import load_scenario, run_all, run_scenario
from .scenarios import claimed_fact, door_visitor_task, door_visitor_world, make_reference_door_engine


def _print_episode(engine: EpisodeEngine) -> int:
    task = engine.active_task
    assert task is not None
    print(f"Task: {task.spec.command}")
    while not task.is_terminal:
        print(json.dumps(engine.tick().to_dict(), ensure_ascii=False))
    print(json.dumps({"status": task.status.value, "steps": task.step_count, "reason": task.terminal_reason, "door_state": engine.world.objects["door.front"].state}, ensure_ascii=False, indent=2))
    return 0


def demo_door() -> int:
    engine = make_reference_door_engine()
    engine.submit_command(door_visitor_task())
    return _print_episode(engine)


def demo_model_contract() -> int:
    fact = claimed_fact("Xiaoman")
    responses = [
        '{"name":"move_to","target":"door.front","parameters":{"acceptance_radius":80}}',
        '{"name":"listen_at","target":"door.front","parameters":{"duration":2}}',
        '{"name":"ask_through","target":"visitor.xiaoman","parameters":{"barrier_id":"door.front","topic":"identity"}}',
        '{"name":"move_to","target":"player","parameters":{"acceptance_radius":120}}',
        json.dumps({"name": "report", "target": "player", "parameters": {"text": "The visitor claims to be Xiaoman.", "facts": [fact]}}, separators=(",", ":")),
    ]
    engine = EpisodeEngine(door_visitor_world(), ModelPolicy(ScriptedTextProvider(responses)), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
    engine.submit_command(door_visitor_task())
    return _print_episode(engine)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wangsheng")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo-door")
    sub.add_parser("demo-model-contract")
    one = sub.add_parser("run-scenario")
    one.add_argument("path")
    one.add_argument("--output-dir", default="artifacts/scripted")
    all_parser = sub.add_parser("run-all-scripted")
    all_parser.add_argument("--scenario-dir", default="scenarios")
    all_parser.add_argument("--output-dir", default="artifacts/scripted")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "demo-door":
        return demo_door()
    if args.command == "demo-model-contract":
        return demo_model_contract()
    if args.command == "run-scenario":
        result = run_scenario(load_scenario(args.path), args.output_dir)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.passed else 1
    if args.command == "run-all-scripted":
        summary = run_all(args.scenario_dir, args.output_dir)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["failed"] == 0 else 1
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
