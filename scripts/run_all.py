from __future__ import annotations

import argparse
import json

from wangsheng.scenario_runner import run_all


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-dir", default="scenarios")
    parser.add_argument("--output-dir", default="artifacts/scripted")
    args = parser.parse_args()
    summary = run_all(args.scenario_dir, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
