from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .scenario_runner import load_scenario, run_scenario
from .trace import normalized_trace, stable_hash


def replay_golden_trace(path: str | Path, *, project_root: str | Path = ".") -> dict[str, Any]:
    golden_path = Path(path)
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    root = Path(project_root)
    scenario_path = root / payload["scenario_path"]
    with TemporaryDirectory(prefix="wangsheng-replay-") as temp_dir:
        result = run_scenario(load_scenario(scenario_path), temp_dir)
        actual_records = normalized_trace(result.trace_path)
    expected_records = payload["records"]
    actual_digest = stable_hash(actual_records)
    expected_digest = payload["expected_digest"]
    return {
        "schema_version": "wangsheng.replay_result.v1",
        "golden_trace": str(golden_path),
        "scenario_id": payload["scenario_id"],
        "scenario_passed": result.passed,
        "records_match": actual_records == expected_records,
        "expected_digest": expected_digest,
        "actual_digest": actual_digest,
        "digest_match": actual_digest == expected_digest,
        "passed": result.passed and actual_records == expected_records and actual_digest == expected_digest,
    }
