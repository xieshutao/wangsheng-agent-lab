#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from wangsheng.memory import KernelConfig, MemoryVersioningKernel

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_TESTS = {f"T{index:02d}" for index in range(1, 20)}
GOLDEN_SHA256 = "c9f5606f37b01a1dc5fe65e0171d66e00a9e447eed7cb728e072a9cabde3159d"
GOLDEN_STATE_DIGEST = "f46dccab2257b789ea7ca05e11288348e6e33daf5f32d135ac30e039f7a516ee"
GOLDEN_OCCURRENCE_DIGEST = "13244a8b76a05e410d5c3d235394abf8c93c1c6a16f51a5c63e82b8884d31d1a"


def test_id_from_name(name: str) -> str | None:
    lowered = name.lower()
    for test_id in sorted(CONTRACT_TESTS):
        if f"test_{test_id.lower()}_" in lowered:
            return test_id
    return None


def run_nonstress_tests() -> tuple[dict[str, object], str]:
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    env["PYTHONPATH"] = src_path + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    with tempfile.TemporaryDirectory(prefix="v070-p5-") as temp_dir:
        junit_path = Path(temp_dir) / "pytest.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/memory",
            "-q",
            "-k",
            "not test_t20_same_world_bounds_stress",
            f"--junitxml={junit_path}",
        ]
        completed = subprocess.run(
            cmd, cwd=ROOT, text=True, capture_output=True, check=False, env=env
        )
        combined = completed.stdout + "\n" + completed.stderr
        seen: set[str] = set()
        passed: set[str] = set()
        failures: list[str] = []
        internal_total = 0
        internal_passed = 0
        if junit_path.is_file():
            xml_root = ET.parse(junit_path).getroot()
            for testcase in xml_root.iter("testcase"):
                name = testcase.get("name") or ""
                failed = testcase.find("failure") is not None or testcase.find("error") is not None
                test_id = test_id_from_name(name)
                if test_id is None:
                    internal_total += 1
                    if not failed:
                        internal_passed += 1
                    else:
                        failures.append(name)
                    continue
                seen.add(test_id)
                if not failed:
                    passed.add(test_id)
                else:
                    failures.append(name)
    summary: dict[str, object] = {
        "expected_contract_tests": sorted(CONTRACT_TESTS),
        "seen_contract_tests": sorted(seen),
        "passed_contract_tests": sorted(passed),
        "internal_tests_total": internal_total,
        "internal_tests_passed": internal_passed,
        "failures": sorted(failures),
        "pytest_returncode": completed.returncode,
        "collection_or_import_error": "ERROR collecting" in combined or "ImportError" in combined,
        "syntax_error": "SyntaxError" in combined,
    }
    summary["status"] = (
        "PASS"
        if seen == CONTRACT_TESTS
        and passed == CONTRACT_TESTS
        and internal_total == internal_passed
        and not failures
        and completed.returncode == 0
        and not summary["collection_or_import_error"]
        and not summary["syntax_error"]
        else "FAIL"
    )
    return summary, combined.rstrip()


def verify_golden() -> dict[str, object]:
    path = ROOT / "golden_traces/v070_xiaoman_three_day.jsonl"
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ] if path.is_file() else []
    contiguous = [item.get("sequence") for item in records] == list(range(1, len(records) + 1))
    state_digest = ""
    occurrence_digest = ""
    replay_error = ""
    try:
        replayed = MemoryVersioningKernel._from_history_trace(  # noqa: SLF001
            records, config=KernelConfig()
        )
        state_digest = replayed.state_digest()
        occurrence_digest = replayed.occurrence_digest()
    except Exception as exc:  # audit output must preserve the exact failure
        replay_error = f"{type(exc).__name__}: {exc}"
    result = {
        "path": str(path.relative_to(ROOT)),
        "records": len(records),
        "expected_sha256": GOLDEN_SHA256,
        "actual_sha256": actual_sha,
        "contiguous_sequences": contiguous,
        "expected_state_digest": GOLDEN_STATE_DIGEST,
        "actual_state_digest": state_digest,
        "expected_occurrence_digest": GOLDEN_OCCURRENCE_DIGEST,
        "actual_occurrence_digest": occurrence_digest,
        "replay_error": replay_error,
    }
    result["status"] = (
        "PASS"
        if actual_sha == GOLDEN_SHA256
        and contiguous
        and state_digest == GOLDEN_STATE_DIGEST
        and occurrence_digest == GOLDEN_OCCURRENCE_DIGEST
        and not replay_error
        else "FAIL"
    )
    return result


def run_stress() -> dict[str, object]:
    kernel = MemoryVersioningKernel()
    summary = kernel.run_same_world_stress(transitions=10_000, seed=7001)
    data = {
        key: getattr(summary, key)
        for key in summary.__dataclass_fields__
    }
    constraints = {
        "transitions": summary.transitions == 10_000,
        "active_lineages": summary.max_active_lineages_per_actor
        <= kernel.config.active_memory_lineages_per_actor,
        "versions_per_lineage": summary.max_active_versions_per_lineage
        <= kernel.config.active_memory_versions_per_lineage,
        "forgetting_cache": summary.max_recent_forgetting_events
        <= kernel.config.recent_forgetting_events_cache,
        "ack_cache": summary.max_recent_acknowledgements
        <= kernel.config.recent_acknowledgement_cache,
        "query_cache": summary.max_belief_query_cache_per_actor
        <= kernel.config.belief_query_cache_per_actor,
        "manifestation_audit": summary.max_manifestation_audit_window
        <= kernel.config.manifestation_audit_window,
        "lineage_cycles": summary.lineage_cycles == 0,
        "partial_commits": summary.partial_commits == 0,
        "digest_mismatches": summary.digest_mismatches == 0,
        "history_trace": summary.history_trace_records >= 10_000,
        "final_replay": summary.final_state_digest == summary.final_replay_digest,
    }
    return {
        "seed": 7001,
        "config": {
            key: getattr(kernel.config, key)
            for key in kernel.config.__dataclass_fields__
        },
        "summary": data,
        "constraints": constraints,
        "status": "PASS" if all(constraints.values()) else "FAIL",
    }


def main() -> int:
    tests, pytest_output = run_nonstress_tests()
    golden = verify_golden()
    stress = run_stress()
    result = {
        "phase": "v0.7-P5",
        "tests_t01_t19": tests,
        "t20_same_world_stress": stress,
        "golden_trace": golden,
    }
    result["status"] = (
        "PASS"
        if tests["status"] == stress["status"] == golden["status"] == "PASS"
        else "FAIL"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n--- pytest output (T01-T19 + internal tests) ---")
    print(pytest_output)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
