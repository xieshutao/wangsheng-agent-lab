from pathlib import Path

from wangsheng.scenario_runner import run_all


def test_v043_holdout_scenarios_are_frozen_and_deterministic(tmp_path: Path) -> None:
    summary = run_all("scenarios_v043_holdout", tmp_path)
    assert summary["scenario_count"] == 5
    assert summary["passed"] == 5
    assert summary["failed"] == 0
    assert summary["hard_violation_count"] == 0
    assert summary["trace_incomplete_count"] == 0
