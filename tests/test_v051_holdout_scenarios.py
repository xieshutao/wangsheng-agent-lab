from pathlib import Path

from wangsheng.scenario_runner import run_all


ROOT = Path(__file__).resolve().parents[1]


def test_v051_holdout_scenarios_are_frozen_and_pass_scripted(tmp_path: Path) -> None:
    summary = run_all(ROOT / "scenarios_v051_holdout", tmp_path)
    assert summary["scenario_count"] == 5
    assert summary["passed"] == 5
    assert summary["hard_violation_count"] == 0
    assert summary["trace_incomplete_count"] == 0
