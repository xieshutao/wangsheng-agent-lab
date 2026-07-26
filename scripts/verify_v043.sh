#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python - <<'PY'
import wangsheng
if wangsheng.__version__ != "0.4.3":
    raise SystemExit(f"expected wangsheng 0.4.3, got {wangsheng.__version__}")
print(f"wangsheng version: {wangsheng.__version__}")
PY

python -m pytest -q

verify_scenarios() {
  local scenario_dir="$1"
  local expected_count="$2"
  local label="$3"
  local out
  out="$(mktemp -d)/${label}"
  python -m wangsheng.cli run-all-scripted \
    --scenario-dir "$scenario_dir" \
    --output-dir "$out" >/tmp/${label}-summary.txt
  python - "$out/summary.json" "$expected_count" "$label" <<'PY'
import json
import sys
from pathlib import Path
summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = int(sys.argv[2])
label = sys.argv[3]
checks = {
    "scenario_count": summary.get("scenario_count") == expected,
    "passed": summary.get("passed") == expected,
    "failed": summary.get("failed") == 0,
    "hard_violation_count": summary.get("hard_violation_count") == 0,
    "trace_incomplete_count": summary.get("trace_incomplete_count") == 0,
}
print(label, json.dumps({key: summary.get(key) for key in checks}, sort_keys=True))
failed = [key for key, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f"{label} verification failed: {failed}")
PY
}

verify_scenarios scenarios 20 wangsheng-v043-regression
verify_scenarios scenarios_v043_holdout 5 wangsheng-v043-holdout

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

echo "v0.4.3 deterministic verification passed."
