#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

EXPECTED_TESTS = {f"T{index:02d}" for index in range(1, 21)}
MARKER = "V0.7_P1_CONTRACT_ONLY"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "pytest", "tests/memory", "-q", "--tb=short"]
    env = os.environ.copy()
    src_path = str(root / "src")
    env["PYTHONPATH"] = src_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    completed = subprocess.run(cmd, cwd=root, text=True, capture_output=True, check=False, env=env)
    combined = completed.stdout + "\n" + completed.stderr

    discovered = set()
    for path in sorted((root / "tests" / "memory").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for test_id in EXPECTED_TESTS:
            if f"test_{test_id.lower()}_" in text:
                discovered.add(test_id)

    marker_count = sum(
        1 for line in combined.splitlines() if line.startswith("FAILED ") and MARKER in line
    )
    summary = {
        "expected_tests": 20,
        "discovered_test_ids": sorted(discovered),
        "pytest_returncode": completed.returncode,
        "not_implemented_marker_occurrences": marker_count,
        "collection_or_import_error": "ERROR collecting" in combined or "ImportError" in combined,
        "syntax_error": "SyntaxError" in combined,
        "status": "PASS"
        if discovered == EXPECTED_TESTS
        and completed.returncode == 1
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
