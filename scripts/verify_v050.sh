#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

python -m pytest -q
python -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios \
  --output-dir "$ROOT/scripted"
python -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios_v043_holdout \
  --output-dir "$ROOT/holdout"
python -m wangsheng.cli replay-trace \
  golden_traces/normal_observe_and_report.json \
  --project-root .
python - <<'PY'
import wangsheng
if wangsheng.__version__ != "0.5.0":
    raise SystemExit(f"unexpected version: {wangsheng.__version__}")
print("version=0.5.0")
PY
