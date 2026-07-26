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
