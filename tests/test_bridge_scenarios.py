from __future__ import annotations

from wangsheng.bridge.scenario_suite import (
    discover_bridge_scenarios,
    run_all_bridge_scenarios,
)


def test_bridge_scenario_matrix_has_exactly_twenty_cases() -> None:
    scenarios = discover_bridge_scenarios("scenarios_bridge_v060")
    assert len(scenarios) == 20
    assert len({scenario.scenario_id for scenario in scenarios}) == 20


def test_all_bridge_scenarios_pass(tmp_path) -> None:
    summary = run_all_bridge_scenarios(
        "scenarios_bridge_v060",
        output_dir=tmp_path,
    )
    assert summary["scenario_count"] == 20
    assert summary["passed_count"] == 20
    assert summary["failed_count"] == 0
    assert summary["all_passed"]
    assert (tmp_path / "summary.json").exists()
