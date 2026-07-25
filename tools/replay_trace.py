from __future__ import annotations

import argparse
import json
from pathlib import Path

from wangsheng.replay import replay_golden_trace


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a WangSheng deterministic golden trace.")
    parser.add_argument("golden_trace")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    result = replay_golden_trace(Path(args.golden_trace), project_root=args.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
