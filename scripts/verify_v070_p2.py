#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

GREEN_TESTS = {f"T{index:02d}" for index in range(1, 9)}
RED_TESTS = {f"T{index:02d}" for index in range(9, 21)}
ALL_TESTS = GREEN_TESTS | RED_TESTS
MARKER = "V0.7_P1_CONTRACT_ONLY"


def test_id_from_name(name: str) -> str | None:
    lowered = name.lower()
    for test_id in sorted(ALL_TESTS):
        if f"test_{test_id.lower()}_" in lowered:
            return test_id
    return None


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    src_path = str(root / "src")
    env["PYTHONPATH"] = src_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    with tempfile.TemporaryDirectory(prefix="v070-p2-") as temp_dir:
        junit_path = Path(temp_dir) / "pytest.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/memory",
            "-q",
            "--tb=long",
            f"--junitxml={junit_path}",
        ]
        completed = subprocess.run(cmd, cwd=root, text=True, capture_output=True, check=False, env=env)
        combined = completed.stdout + "\n" + completed.stderr

        seen: set[str] = set()
        passed: set[str] = set()
        failed: dict[str, str] = {}
        if junit_path.is_file():
            xml_root = ET.parse(junit_path).getroot()
            for testcase in xml_root.iter("testcase"):
                test_id = test_id_from_name(testcase.get("name") or "")
                if test_id is None:
                    continue
                seen.add(test_id)
                failure = testcase.find("failure")
                error = testcase.find("error")
                if failure is None and error is None:
                    passed.add(test_id)
                else:
                    node = failure if failure is not None else error
                    assert node is not None
                    failed[test_id] = (node.get("message") or "") + "\n" + (node.text or "")

    marker_failures = {test_id for test_id, body in failed.items() if MARKER in body}
    unexpected_failures = sorted(set(failed) - marker_failures)
    summary = {
        "expected_green": sorted(GREEN_TESTS),
        "expected_controlled_red": sorted(RED_TESTS),
        "seen": sorted(seen),
        "passed": sorted(passed),
        "failed": sorted(failed),
        "marker_failures": sorted(marker_failures),
        "unexpected_failures": unexpected_failures,
        "pytest_returncode": completed.returncode,
        "collection_or_import_error": "ERROR collecting" in combined or "ImportError" in combined,
        "syntax_error": "SyntaxError" in combined,
    }
    summary["status"] = (
        "PASS"
        if seen == ALL_TESTS
        and passed == GREEN_TESTS
        and set(failed) == RED_TESTS
        and marker_failures == RED_TESTS
        and not unexpected_failures
        and completed.returncode == 1
        and "ERROR collecting" not in combined
        and "ImportError" not in combined
        and "SyntaxError" not in combined
        else "FAIL"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n--- pytest output ---")
    print(combined.rstrip())
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
