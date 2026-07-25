from __future__ import annotations

import argparse
import json

from .engine import EpisodeEngine
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .gateway import Gateway
from .policy import ModelPolicy
from .providers import ScriptedTextProvider
from .scenarios import (
    door_visitor_task,
    door_visitor_world,
    make_reference_door_engine,
)


def _print_episode(engine: EpisodeEngine) -> int:
    task = engine.active_task
    assert task is not None
    print(f"Task: {task.spec.command}")
    while not task.is_terminal:
        observation = engine.tick()
        print(json.dumps(observation.to_dict(), ensure_ascii=False))

    print(
        json.dumps(
            {
                "status": task.status.value,
                "steps": task.step_count,
                "reason": task.terminal_reason,
                "door_state": engine.world.objects["front_door"].state,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def demo_door() -> int:
    engine = make_reference_door_engine()
    engine.submit_command(door_visitor_task())
    return _print_episode(engine)


def demo_model_contract() -> int:
    provider = ScriptedTextProvider(
        [
            '{"name":"move_to","target":"front_door","parameters":{}}',
            '{"name":"listen_at","target":"front_door","parameters":{}}',
            '{"name":"talk_to","target":"visitor_b","parameters":{}}',
            '{"name":"return_to","target":"player","parameters":{}}',
            (
                '{"name":"report","target":null,"parameters":'
                '{"text":"The visitor claims to be Xiaoman. I did not open the door."}}'
            ),
        ]
    )
    engine = EpisodeEngine(
        door_visitor_world(),
        ModelPolicy(provider),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    engine.submit_command(door_visitor_task())
    return _print_episode(engine)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wangsheng")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("demo-door")
    subparsers.add_parser("demo-model-contract")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "demo-door":
        return demo_door()
    if args.command == "demo-model-contract":
        return demo_model_contract()
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
