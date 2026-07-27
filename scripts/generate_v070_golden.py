#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from wangsheng.memory import MemoryVersioningKernel
from wangsheng.memory.kernel import _canonical_json

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "specs/v0.7/scenarios/xiaoman_three_day_kernel_fixture_v0.7.json"
GOLDEN = ROOT / "golden_traces/v070_xiaoman_three_day.jsonl"
SHA_FILE = ROOT / "golden_traces/v070_xiaoman_three_day.sha256"


def generated_bytes() -> bytes:
    fixture = MemoryVersioningKernel._load_xiaoman_fixture(FIXTURE)  # noqa: SLF001
    kernel, _ = MemoryVersioningKernel._build_xiaoman_day3_branch(  # noqa: SLF001
        fixture, "OLD_RESIDENT_CONTINUATION"
    )
    return "".join(_canonical_json(item) + "\n" for item in kernel._history_trace).encode(  # noqa: SLF001
        "utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite the frozen Golden Trace; review the resulting diff before commit",
    )
    args = parser.parse_args()
    payload = generated_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if args.write:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(payload)
        SHA_FILE.write_text(f"{digest}  {GOLDEN.name}\n", encoding="utf-8")
        print(f"wrote {GOLDEN.relative_to(ROOT)} ({len(payload)} bytes, sha256={digest})")
        return 0
    if not GOLDEN.is_file() or not SHA_FILE.is_file():
        print("Golden Trace or checksum file is missing")
        return 2
    declared = SHA_FILE.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    if payload != GOLDEN.read_bytes() or digest != declared or actual != declared:
        print(
            "Golden Trace mismatch: "
            f"generated={digest} declared={declared} actual={actual}"
        )
        return 2
    print(f"PASS sha256={actual} records={payload.count(chr(10).encode())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
