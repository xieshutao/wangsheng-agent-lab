#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python - <<'PY'
import wangsheng
if wangsheng.__version__ != "0.4.2":
    raise SystemExit(f"expected wangsheng 0.4.2, got {wangsheng.__version__}")
print(f"wangsheng version: {wangsheng.__version__}")
PY

python -m pytest -q

OUT="$(mktemp -d)/wangsheng-v042-scripted"
python -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios \
  --output-dir "$OUT" >/tmp/wangsheng-v042-scripted-summary.txt

python - "$OUT/summary.json" <<'PY'
import json
import sys
from pathlib import Path
summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
checks = {
    "scenario_count": summary.get("scenario_count") == 20,
    "passed": summary.get("passed") == 20,
    "failed": summary.get("failed") == 0,
    "hard_violation_count": summary.get("hard_violation_count") == 0,
    "trace_incomplete_count": summary.get("trace_incomplete_count") == 0,
}
print(json.dumps({key: summary.get(key) for key in checks}, indent=2, sort_keys=True))
failed = [key for key, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f"deterministic verification failed: {failed}")
PY

REPLAY="$(python -m wangsheng.cli replay-trace golden_traces/normal_observe_and_report.json)"
printf '%s\n' "$REPLAY"
python - "$REPLAY" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
required = ("passed", "records_match", "digest_match")
failed = [key for key in required if payload.get(key) is not True]
if failed:
    raise SystemExit(f"Golden Trace verification failed: {failed}")
PY

echo "v0.4.2 deterministic verification passed."
