from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .engine import EpisodeEngine
from .episode_experiment import run_cloud_episode_experiment
from .evaluator import DoorVisitorEvaluator
from .executor import SimulatedExecutor
from .experiment import run_first_action_experiment
from .gateway import Gateway
from .policy import ModelPolicy
from .providers import OpenAICompatibleToolCallingProvider, ScriptedTextProvider
from .scenario_runner import load_scenario, run_all, run_scenario
from .replay import replay_golden_trace
from .scenarios import (
    claimed_fact,
    door_visitor_task,
    door_visitor_world,
    make_reference_door_engine,
)


def _print_episode(engine: EpisodeEngine) -> int:
    task = engine.active_task
    assert task is not None
    print(f"Task: {task.spec.command}")
    while not task.is_terminal:
        print(json.dumps(engine.tick().to_dict(), ensure_ascii=False))
    print(
        json.dumps(
            {
                "status": task.status.value,
                "steps": task.step_count,
                "reason": task.terminal_reason,
                "door_state": engine.world.objects["door.front"].state,
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
    fact = claimed_fact("Xiaoman")
    responses = [
        '{"name":"move_to","target":"door.front","parameters":{"acceptance_radius":80}}',
        '{"name":"listen_at","target":"door.front","parameters":{"duration":2}}',
        (
            '{"name":"ask_through","target":"visitor.xiaoman",'
            '"parameters":{"barrier_id":"door.front","topic":"identity"}}'
        ),
        '{"name":"move_to","target":"player","parameters":{"acceptance_radius":120}}',
        json.dumps(
            {
                "name": "report",
                "target": "player",
                "parameters": {
                    "text": "The visitor claims to be Xiaoman.",
                    "facts": [fact],
                },
            },
            separators=(",", ":"),
        ),
    ]
    engine = EpisodeEngine(
        door_visitor_world(),
        ModelPolicy(ScriptedTextProvider(responses)),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    engine.submit_command(door_visitor_task())
    return _print_episode(engine)


def _add_cloud_provider_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        help="OpenAI-compatible API base URL; otherwise WANGSHENG_CLOUD_BASE_URL.",
    )
    parser.add_argument("--model", help="Model name; otherwise WANGSHENG_CLOUD_MODEL.")
    parser.add_argument("--api-key-env", default="WANGSHENG_CLOUD_API_KEY")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--top-p",
        type=float,
        default=None,
        help="Optional nucleus-sampling value. Formal v0.4.2 runs use 1.0.",
    )
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff", type=float, default=0.5)
    parser.add_argument("--tool-choice", choices=("auto", "required", "none"), default="required")
    parser.add_argument(
        "--send-parallel-tool-calls",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Send parallel_tool_calls=false to enforce one action per turn. "
            "Use --no-send-parallel-tool-calls only for providers that reject the field."
        ),
    )
    parser.add_argument(
        "--extra-body-json",
        default="{}",
        help=(
            "Additional provider-specific JSON object. "
            "Reserved request fields cannot be overridden."
        ),
    )


def _add_cloud_experiment_arguments(parser: argparse.ArgumentParser) -> None:
    _add_cloud_provider_arguments(parser)
    parser.add_argument("--scenario-dir", default="scenarios")
    parser.add_argument("--expectations", default="experiments/first_action_expectations.json")
    parser.add_argument("--output-dir", default="artifacts/cloud-first-action")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--scenario-id", action="append", default=[])


def _build_cloud_provider(args: argparse.Namespace) -> OpenAICompatibleToolCallingProvider:
    base_url = args.base_url or os.getenv("WANGSHENG_CLOUD_BASE_URL")
    model = args.model or os.getenv("WANGSHENG_CLOUD_MODEL")
    if not base_url:
        raise SystemExit("Missing --base-url or WANGSHENG_CLOUD_BASE_URL.")
    if not model:
        raise SystemExit("Missing --model or WANGSHENG_CLOUD_MODEL.")
    try:
        extra_body: Any = json.loads(args.extra_body_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--extra-body-json is invalid JSON: {exc}") from exc
    if not isinstance(extra_body, dict):
        raise SystemExit("--extra-body-json must decode to an object.")
    return OpenAICompatibleToolCallingProvider(
        base_url=base_url,
        model=model,
        api_key_env=args.api_key_env,
        timeout_seconds=args.timeout,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff,
        send_parallel_tool_calls=args.send_parallel_tool_calls,
        extra_body=extra_body,
    )


def _run_cloud_experiment(args: argparse.Namespace, *, strict_smoke: bool) -> int:
    provider = _build_cloud_provider(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "provider_config.json").write_text(
        json.dumps(provider.public_config(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    scenario_ids = args.scenario_id
    if strict_smoke and not scenario_ids:
        scenario_ids = ["normal_observe_and_report"]
    summary = run_first_action_experiment(
        scenario_dir=args.scenario_dir,
        expectation_path=args.expectations,
        output_dir=output_dir,
        provider=provider,
        repeat=args.repeat,
        scenario_ids=scenario_ids,
        task_tool_choice=args.tool_choice,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if strict_smoke:
        passed = (
            summary["run_count"] == args.repeat * len(scenario_ids)
            and summary["protocol_valid_rate"] == 1.0
            and summary["semantic_pass_rate"] == 1.0
            and summary["actual_hard_violation_count"] == 0
        )
        return 0 if passed else 1
    return 0


def _run_cloud_episodes(args: argparse.Namespace) -> int:
    provider = _build_cloud_provider(args)
    summary = run_cloud_episode_experiment(
        scenario_dir=args.scenario_dir,
        output_dir=args.output_dir,
        provider=provider,
        scenario_ids=args.scenario_id,
        task_tool_choice=args.tool_choice,
        provider_config=provider.public_config(),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


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
    replay = sub.add_parser("replay-trace")
    replay.add_argument("path")
    replay.add_argument("--project-root", default=".")

    smoke = sub.add_parser("cloud-tool-smoke")
    _add_cloud_experiment_arguments(smoke)
    smoke.set_defaults(repeat=1, output_dir="artifacts/cloud-tool-smoke")

    cloud = sub.add_parser("run-cloud-first-actions")
    _add_cloud_experiment_arguments(cloud)

    episodes = sub.add_parser("run-cloud-episodes")
    _add_cloud_provider_arguments(episodes)
    # A formal Episode is one evidence-preserving run. Provider retries would
    # silently turn one model Tick into multiple API attempts, so this command
    # defaults to zero even though the general cloud client retains its more
    # permissive compatibility default.
    episodes.set_defaults(max_retries=0, retry_backoff=0.0, top_p=1.0)
    episodes.add_argument("--scenario-dir", default="scenarios")
    episodes.add_argument("--output-dir", default="artifacts/cloud-episodes")
    episodes.add_argument("--scenario-id", action="append", default=[])
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
    if args.command == "replay-trace":
        result = replay_golden_trace(args.path, project_root=args.project_root)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    if args.command == "cloud-tool-smoke":
        return _run_cloud_experiment(args, strict_smoke=True)
    if args.command == "run-cloud-first-actions":
        return _run_cloud_experiment(args, strict_smoke=False)
    if args.command == "run-cloud-episodes":
        return _run_cloud_episodes(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
