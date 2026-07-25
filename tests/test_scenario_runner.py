import json
from pathlib import Path

from wangsheng.scenario_runner import discover_scenarios, load_scenario, run_all, run_scenario


def test_twenty_scenarios_are_discoverable():
    assert len(discover_scenarios("scenarios")) == 20


def test_each_scenario_runs_and_writes_complete_trace(tmp_path):
    for path in discover_scenarios("scenarios"):
        result = run_scenario(load_scenario(path), tmp_path)
        assert result.passed, (result.scenario_id, result.failures)
        assert result.trace_complete
        assert Path(result.trace_path).exists()


def test_run_all_reports_100_percent_and_zero_hard_violations(tmp_path):
    summary = run_all("scenarios", tmp_path)
    assert summary["scenario_count"] == 20
    assert summary["passed"] == 20
    assert summary["failed"] == 0
    assert summary["pass_rate"] == 1.0
    assert summary["hard_violation_count"] == 0
    assert summary["trace_incomplete_count"] == 0
    saved = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert saved["passed"] == 20


def test_failure_classification_is_reported(tmp_path):
    summary = run_all("scenarios", tmp_path)
    categories = summary["failure_classification"]
    assert categories["hard_constraint"] >= 1
    assert categories["knowledge_violation"] >= 1
    assert categories["loop"] == 1
    assert categories["max_steps"] == 1
    assert categories["other"] == 0


def test_terminal_scenario_prevents_post_completion_mutation(tmp_path):
    path = next(path for path in discover_scenarios("scenarios") if "terminal_task" in path.name)
    result = run_scenario(load_scenario(path), tmp_path)
    assert result.passed
    assert result.status == "succeeded"
