from __future__ import annotations

import argparse
import json
from pathlib import Path

from wangsheng.result_audit import audit_v051_result_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute the v0.5.1 renderer/dialogue integrity audit from private traces."
    )
    parser.add_argument("result_root", help="Extracted private v0.5.1 result directory")
    parser.add_argument("--output", help="Write corrected audit JSON to this path")
    parser.add_argument("--source-archive-sha256", help="Optional SHA-256 of the private source archive")
    args = parser.parse_args()

    payload = audit_v051_result_root(
        args.result_root,
        source_archive_sha256=args.source_archive_sha256,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
