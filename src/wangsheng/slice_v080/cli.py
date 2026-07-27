from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import SliceProtocolError, XiaomanThreeDaySlice


DEMO_SCRIPT = [
    ("a01", "listen_at_door", {}),
    ("a02", "inspect_paper_crane", {}),
    ("a03", "ask_qingyan", {}),
    ("a04", "advance_to_day2", {}),
    ("a05", "record_night1", {"choice_id": "CAND_D1_NAME_SELF_REPORT"}),
    ("a06", "review_day2_change", {}),
    ("a07", "advance_to_day3", {}),
    ("a08", "read_archive", {}),
    ("a09", "inspect_body_continuity", {}),
    ("a10", "ask_xiaoman_consent", {}),
    ("a11", "decide_day3", {"outcome_id": "OLD_RESIDENT_CONTINUATION"}),
]


def run_demo(fixture: Path) -> int:
    runtime = XiaomanThreeDaySlice(fixture, session_id="demo-xiaoman-three-day")
    for action_id, command, parameters in DEMO_SCRIPT:
        result = runtime.command(action_id=action_id, command=command, parameters=parameters)
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    print(json.dumps({"final": runtime.view()}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("specs/v0.7/scenarios/xiaoman_three_day_kernel_fixture_v0.7.json"))
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    try:
        raise SystemExit(run_demo(args.fixture))
    except SliceProtocolError as exc:
        print(json.dumps({"status": "error", "reason_code": exc.reason_code, "message": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
