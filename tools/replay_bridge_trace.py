#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wangsheng.bridge.transport import JsonlTraceTransport, replay_message_stream


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a v0.6 bridge JSONL trace.")
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    messages = JsonlTraceTransport(args.trace).read_all()
    result = replay_message_stream(messages)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
