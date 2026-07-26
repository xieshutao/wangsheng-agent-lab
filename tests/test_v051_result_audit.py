from __future__ import annotations

import json
from pathlib import Path

from wangsheng.result_audit import audit_v051_result_root


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_minimum_summaries(root: Path) -> None:
    summaries = {
        "summary_regression.json": {"episode_count": 20},
        "summary_legacy_holdout.json": {"episode_count": 5},
        "summary_reliability_holdout.json": {"episode_count": 5, "pass_rate": 0.8},
        "summary_legacy25.json": {"episode_count": 25, "pass_rate": 0.92},
        "summary_overall30.json": {
            "episode_count": 30,
            "pass_count": 27,
            "protocol_valid_rate": 1.0,
            "grounded_rate": 1.0,
            "actual_hard_violation_count": 0,
            "hallucinated_target_count": 0,
            "knowledge_violation_count": 0,
            "provider_error_count": 0,
            "trace_incomplete_count": 0,
            "repeated_action_loop_count": 1,
        },
    }
    for name, payload in summaries.items():
        _write_json(root / name, payload)
    (root / "synthetic_contract_post.jsonl").write_text(
        "\n".join(json.dumps({"passed": True, "request": i}) for i in range(5)) + "\n",
        encoding="utf-8",
    )


def test_audit_distinguishes_rejected_and_executed_reports(tmp_path: Path) -> None:
    root = tmp_path / "results"
    trace = root / "sets" / "regression" / "traces" / "one.jsonl"
    trace.parent.mkdir(parents=True)
    events = [
        {
            "event_type": "tick",
            "action_request": {"name": "report", "arguments": {"fact_ids": ["fact.one"]}},
            "gateway": {"status": "rejected"},
            "executor": {"status": "not_run"},
            "observation": {"source": "gateway", "success": False, "evidence": {}},
        },
        {
            "event_type": "tick",
            "action_request": {"name": "report", "arguments": {"fact_ids": ["fact.one"]}},
            "gateway": {"status": "allowed"},
            "executor": {"status": "success"},
            "observation": {
                "source": "executor",
                "success": True,
                "evidence": {"rendered_by": "deterministic_fact_renderer"},
            },
        },
        {
            "event_type": "dialogue_turn",
            "model": {"request": {"tools": []}, "tool_call_count": 0},
            "state_delta": {},
            "world_before": {"x": 1},
            "world_after": {"x": 1},
        },
    ]
    trace.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    _write_minimum_summaries(root)

    audit = audit_v051_result_root(root)

    assert audit["passed"] is True
    assert audit["report_request_count"] == 2
    assert audit["report_gateway_rejected_count"] == 1
    assert audit["report_executor_success_count"] == 1
    assert audit["renderer_verified_count"] == 1
    assert audit["dialogue_turn_count"] == 1
    assert audit["corrected_acceptance"]["all_gates_passed"] is True


def test_audit_rejects_missing_renderer(tmp_path: Path) -> None:
    root = tmp_path / "results"
    trace = root / "sets" / "regression" / "traces" / "one.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_text(
        json.dumps(
            {
                "event_type": "tick",
                "action_request": {"name": "report", "arguments": {"fact_ids": ["fact.one"]}},
                "gateway": {"status": "allowed"},
                "executor": {"status": "success"},
                "observation": {"source": "executor", "success": True, "evidence": {}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_minimum_summaries(root)

    audit = audit_v051_result_root(root)

    assert audit["passed"] is False
    assert audit["renderer_missing_count"] == 1
    assert audit["corrected_acceptance"]["all_gates_passed"] is False


def test_audit_rejects_dialogue_world_mutation(tmp_path: Path) -> None:
    root = tmp_path / "results"
    trace = root / "sets" / "regression" / "traces" / "one.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_text(
        json.dumps(
            {
                "event_type": "dialogue_turn",
                "model": {"request": {"tools": []}, "tool_call_count": 0},
                "state_delta": {"time": {"from": 0, "to": 1}},
                "world_before": {"time": 0},
                "world_after": {"time": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_minimum_summaries(root)

    audit = audit_v051_result_root(root)

    assert audit["passed"] is False
    assert audit["dialogue_state_delta_nonempty_count"] == 1
    assert audit["dialogue_world_changed_count"] == 1
