from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_soak_module():
    path = Path("tools/run_bridge_soak.py")
    spec = importlib.util.spec_from_file_location("run_bridge_soak", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bridge_soak_small_contract() -> None:
    module = _load_soak_module()
    summary = module.run_soak(
        scheduler_events=200,
        action_lifecycles=50,
        save_load_cycles=10,
    )
    assert summary["passed"]
    assert summary["invalid_lifecycle_transitions"] == 0
    assert summary["save_digest_mismatches"] == 0
    assert summary["retained_message_count"] <= summary["retained_message_limit"]
    assert summary["max_active_actions"] <= 1
    assert summary["active_actions_final"] == 0
    assert summary["max_terminal_action_cache"] <= summary["terminal_action_cache_limit"]
    assert summary["max_request_cache"] <= summary["request_cache_limit"]
    assert summary["max_report_history"] <= summary["report_history_limit"]
    assert summary["terminal_cache_clear_mismatches"] == 0
