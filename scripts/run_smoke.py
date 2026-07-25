from __future__ import annotations

import json

from wangsheng.scenario_runner import load_scenario, run_scenario


def main() -> int:
    result = run_scenario(load_scenario("scenarios/01_normal_visitor.json"), "artifacts/smoke")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
