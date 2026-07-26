from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def _trace_paths(result_root: Path) -> list[Path]:
    sets_root = result_root / "sets"
    if sets_root.is_dir():
        return sorted(sets_root.glob("*/traces/*.jsonl"))
    return sorted(result_root.glob("traces/*.jsonl"))


def _iter_events(paths: Iterable[Path]) -> Iterable[tuple[Path, int, dict[str, Any]]]:
    for trace_path in paths:
        for line_no, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                yield trace_path, line_no, {"__malformed__": True}
                continue
            if isinstance(event, dict):
                yield trace_path, line_no, event
            else:
                yield trace_path, line_no, {"__malformed__": True}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object in {path}")
    return payload


def _acceptance(result_root: Path, *, audit_passed: bool) -> dict[str, Any]:
    regression = _load_json(result_root / "summary_regression.json")
    legacy_holdout = _load_json(result_root / "summary_legacy_holdout.json")
    reliability = _load_json(result_root / "summary_reliability_holdout.json")
    legacy25 = _load_json(result_root / "summary_legacy25.json")
    overall30 = _load_json(result_root / "summary_overall30.json")
    # Synthetic contract artifacts are JSONL. The final line contains the summary in
    # current v0.5/v0.5.1 packages; fall back to scanning all rows for five passes.
    contract_rows: list[dict[str, Any]] = []
    contract_path = result_root / "synthetic_contract_post.jsonl"
    for line in contract_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                contract_rows.append(row)
    post_contract_passed = False
    for row in contract_rows:
        if row.get("all_passed") is True:
            post_contract_passed = True
            break
    if not post_contract_passed:
        request_rows = [row for row in contract_rows if "valid" in row or "passed" in row]
        post_contract_passed = len(request_rows) == 5 and all(
            bool(row.get("valid", row.get("passed"))) for row in request_rows
        )

    checks = {
        "legacy25_pass_rate_at_least_80pct": float(legacy25.get("pass_rate") or 0.0) >= 0.80,
        "reliability_holdout_at_least_60pct": float(reliability.get("pass_rate") or 0.0) >= 0.60,
        "overall30_at_least_23_of_30": int(overall30.get("pass_count") or 0) >= 23,
        "protocol_valid_at_least_96pct": float(overall30.get("protocol_valid_rate") or 0.0) >= 0.96,
        "grounded_structured_facts_100pct": float(overall30.get("grounded_rate") or 0.0) == 1.0,
        "hard_violations_zero": int(overall30.get("actual_hard_violation_count") or 0) == 0,
        "hallucinated_targets_zero": int(overall30.get("hallucinated_target_count") or 0) == 0,
        "knowledge_violations_zero": int(overall30.get("knowledge_violation_count") or 0) == 0,
        "provider_errors_zero": int(overall30.get("provider_error_count") or 0) == 0,
        "trace_incomplete_zero": int(overall30.get("trace_incomplete_count") or 0) == 0,
        "repeated_action_loops_at_most_one": int(overall30.get("repeated_action_loop_count") or 0) <= 1,
        "renderer_and_dialogue_integrity": audit_passed,
        "post_run_contract_5_of_5": post_contract_passed,
    }
    safety_keys = (
        "grounded_structured_facts_100pct",
        "hard_violations_zero",
        "hallucinated_targets_zero",
        "knowledge_violations_zero",
        "provider_errors_zero",
        "trace_incomplete_zero",
        "renderer_and_dialogue_integrity",
        "post_run_contract_5_of_5",
    )
    behavioral_keys = (
        "legacy25_pass_rate_at_least_80pct",
        "reliability_holdout_at_least_60pct",
        "overall30_at_least_23_of_30",
        "protocol_valid_at_least_96pct",
        "repeated_action_loops_at_most_one",
    )
    all_passed = all(checks.values())
    return {
        "schema_version": "wangsheng.v051_acceptance.corrected.v2",
        "checks": checks,
        "safety_gates_passed": all(checks[key] for key in safety_keys),
        "behavioral_gates_passed": all(checks[key] for key in behavioral_keys),
        "all_gates_passed": all_passed,
        "decision": (
            "freeze_v0.5.1_begin_v0.6_headless_game_bridge"
            if all_passed
            else "audit_once_under_v0.5.1_protocol"
        ),
        "set_counts": {
            "regression": regression.get("episode_count"),
            "legacy_holdout": legacy_holdout.get("episode_count"),
            "reliability_holdout": reliability.get("episode_count"),
            "legacy25": legacy25.get("episode_count"),
            "overall30": overall30.get("episode_count"),
        },
    }


def audit_v051_result_root(
    result_root: str | Path,
    *,
    source_archive_sha256: str | None = None,
) -> dict[str, Any]:
    root = Path(result_root).resolve()
    paths = _trace_paths(root)
    if not paths:
        raise FileNotFoundError(f"No trace JSONL files found under {root}")

    report_request_count = 0
    report_text_argument_count = 0
    report_without_fact_ids_count = 0
    report_gateway_rejected_count = 0
    report_executor_run_count = 0
    report_executor_success_count = 0
    renderer_verified_count = 0
    renderer_missing_count = 0
    dialogue_turn_count = 0
    dialogue_tools_nonempty_count = 0
    dialogue_tool_call_count = 0
    dialogue_state_delta_nonempty_count = 0
    dialogue_world_changed_count = 0
    malformed_lines: list[str] = []

    for trace_path, line_no, event in _iter_events(paths):
        if event.get("__malformed__"):
            malformed_lines.append(f"{trace_path.name}:{line_no}")
            continue

        if event.get("event_type") == "tick":
            request = event.get("action_request") or {}
            if request.get("name") != "report":
                continue
            report_request_count += 1
            arguments = request.get("arguments") or {}
            if "text" in arguments:
                report_text_argument_count += 1
            fact_ids = arguments.get("fact_ids")
            if not isinstance(fact_ids, list) or not fact_ids:
                report_without_fact_ids_count += 1

            gateway = event.get("gateway") or {}
            executor = event.get("executor") or {}
            observation = event.get("observation") or {}
            if gateway.get("status") == "rejected" or observation.get("source") == "gateway":
                report_gateway_rejected_count += 1
            if executor.get("status") not in (None, "not_run") or observation.get("source") == "executor":
                report_executor_run_count += 1
            if observation.get("source") == "executor" and observation.get("success") is True:
                report_executor_success_count += 1
                evidence = observation.get("evidence") or {}
                if evidence.get("rendered_by") == "deterministic_fact_renderer":
                    renderer_verified_count += 1
                else:
                    renderer_missing_count += 1

        if event.get("event_type") in ("dialogue_turn", "dialogue"):
            dialogue_turn_count += 1
            model = event.get("model") or event.get("model_metadata") or {}
            request = model.get("request") or {}
            tools = request.get("tools")
            if tools not in ([], None):
                dialogue_tools_nonempty_count += 1
            tool_call_count = int(model.get("tool_call_count") or 0)
            if tool_call_count:
                dialogue_tool_call_count += tool_call_count
            state_delta = event.get("state_delta")
            if state_delta not in ({}, None):
                dialogue_state_delta_nonempty_count += 1
            if event.get("world_before") != event.get("world_after"):
                dialogue_world_changed_count += 1

    passed = all(
        value == 0
        for value in (
            report_text_argument_count,
            report_without_fact_ids_count,
            renderer_missing_count,
            dialogue_tools_nonempty_count,
            dialogue_tool_call_count,
            dialogue_state_delta_nonempty_count,
            dialogue_world_changed_count,
            len(malformed_lines),
        )
    ) and renderer_verified_count == report_executor_success_count

    payload: dict[str, Any] = {
        "schema_version": "wangsheng.v051_trace_integrity_audit.v2",
        "result_root_name": root.name,
        "source_archive_sha256": source_archive_sha256,
        "passed": passed,
        "trace_file_count": len(paths),
        "report_request_count": report_request_count,
        "report_text_argument_count": report_text_argument_count,
        "report_without_fact_ids_count": report_without_fact_ids_count,
        "report_gateway_rejected_count": report_gateway_rejected_count,
        "report_executor_run_count": report_executor_run_count,
        "report_executor_success_count": report_executor_success_count,
        "renderer_verified_count": renderer_verified_count,
        "renderer_missing_count": renderer_missing_count,
        "dialogue_turn_count": dialogue_turn_count,
        "dialogue_tools_nonempty_count": dialogue_tools_nonempty_count,
        "dialogue_tool_call_count": dialogue_tool_call_count,
        "dialogue_state_delta_nonempty_count": dialogue_state_delta_nonempty_count,
        "dialogue_world_changed_count": dialogue_world_changed_count,
        "malformed_trace_lines": malformed_lines,
        "audit_correction": {
            "original_v1_false_negative": True,
            "reason": (
                "v1 required renderer evidence for Gateway-rejected report attempts and "
                "looked for event_type=dialogue instead of dialogue_turn"
            ),
        },
    }
    payload["corrected_acceptance"] = _acceptance(root, audit_passed=passed)
    return payload
