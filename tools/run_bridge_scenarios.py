#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from wangsheng.bridge.scenario_suite import run_all_bridge_scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic v0.6 bridge scenarios.")
    parser.add_argument("--scenario-dir", default="scenarios_bridge_v060")
    parser.add_argument("--output-dir", default="artifacts/bridge-v060-scenarios")
    args = parser.parse_args()
    summary = run_all_bridge_scenarios(args.scenario_dir, output_dir=args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
