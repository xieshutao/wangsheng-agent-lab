#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

EXPECTED_TESTS = {f"T{index:02d}" for index in range(1, 21)}
MARKER = "V0.7_P1_CONTRACT_ONLY"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    src_path = str(root / "src")
    env["PYTHONPATH"] = src_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    with tempfile.TemporaryDirectory(prefix="v070-p1-red-") as temp_dir:
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

        failure_bodies: list[str] = []
        if junit_path.is_file():
            xml_root = ET.parse(junit_path).getroot()
            for testcase in xml_root.iter("testcase"):
                failure = testcase.find("failure")
                if failure is not None:
                    failure_bodies.append((failure.get("message") or "") + "\n" + (failure.text or ""))

    discovered = set()
    for path in sorted((root / "tests" / "memory").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for test_id in EXPECTED_TESTS:
            if f"test_{test_id.lower()}_" in text:
                discovered.add(test_id)

    marker_count = sum(MARKER in body for body in failure_bodies)
    summary = {
        "expected_tests": 20,
        "discovered_test_ids": sorted(discovered),
        "pytest_returncode": completed.returncode,
        "junit_failure_count": len(failure_bodies),
        "not_implemented_marker_occurrences": marker_count,
        "collection_or_import_error": "ERROR collecting" in combined or "ImportError" in combined,
        "syntax_error": "SyntaxError" in combined,
        "status": "PASS"
        if discovered == EXPECTED_TESTS
        and completed.returncode == 1
        and len(failure_bodies) == 20
        and marker_count == 20
        and "20 failed" in combined
        and "ERROR collecting" not in combined
        and "ImportError" not in combined
        and "SyntaxError" not in combined
        else "FAIL",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n--- pytest output ---")
    print(combined.rstrip())
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
