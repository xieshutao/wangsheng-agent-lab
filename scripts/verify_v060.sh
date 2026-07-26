#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "${WANGSHENG_PYTHON:-}" ]]; then
  PY="$WANGSHENG_PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  printf 'ERROR: no Python interpreter found\n' >&2
  exit 1
fi

PY="$(realpath "$PY")"
[[ -x "$PY" ]] || { printf 'ERROR: Python is not executable: %s\n' "$PY" >&2; exit 1; }

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

find "$REPO_ROOT" \
  \( -path "$REPO_ROOT/.git" -o -path "$REPO_ROOT/.venv" -o -path "$REPO_ROOT/venv" \) -prune -o \
  -type d -name __pycache__ -exec rm -rf {} +
find "$REPO_ROOT" -type f -name '*.py[co]' \
  -not -path "$REPO_ROOT/.git/*" \
  -not -path "$REPO_ROOT/.venv/*" \
  -not -path "$REPO_ROOT/venv/*" \
  -delete

"$PY" - <<'PY'
from pathlib import Path
import sys
import wangsheng
from wangsheng.bridge import PROTOCOL_VERSION

root = Path.cwd().resolve()
module = Path(wangsheng.__file__).resolve()
if root not in module.parents:
    raise SystemExit(
        f"wangsheng import is not from current worktree: module={module} root={root}"
    )
if wangsheng.__version__ != "0.6.0":
    raise SystemExit(f"unexpected version: {wangsheng.__version__}")
if PROTOCOL_VERSION != "0.6":
    raise SystemExit(f"unexpected bridge protocol: {PROTOCOL_VERSION}")
print(f"python={Path(sys.executable).resolve()}")
print(f"wangsheng_module={module}")
print("version=0.6.0")
print("bridge_protocol=0.6")
PY

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

"$PY" -m pytest -q
"$PY" -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios \
  --output-dir "$ROOT/scripted"
"$PY" -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios_v043_holdout \
  --output-dir "$ROOT/holdout-v043"
"$PY" -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios_v051_holdout \
  --output-dir "$ROOT/holdout-v051"
"$PY" -m wangsheng.cli replay-trace \
  golden_traces/normal_observe_and_report.json \
  --project-root .
"$PY" tools/run_bridge_scenarios.py \
  --scenario-dir scenarios_bridge_v060 \
  --output-dir "$ROOT/bridge-scenarios" \
  > "$ROOT/bridge-scenarios-console.json"
"$PY" tools/run_bridge_soak.py \
  --scheduler-events 10000 \
  --action-lifecycles 1000 \
  --save-load-cycles 100 \
  --output "$ROOT/bridge-soak.json" \
  > "$ROOT/bridge-soak-console.json"

"$PY" - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
scenario_summary = json.loads((root / "bridge-scenarios" / "summary.json").read_text())
soak_summary = json.loads((root / "bridge-soak.json").read_text())
if scenario_summary.get("scenario_count") != 20 or not scenario_summary.get("all_passed"):
    raise SystemExit(f"bridge scenarios failed: {scenario_summary}")
if not soak_summary.get("passed"):
    raise SystemExit(f"bridge soak failed: {soak_summary}")
print("bridge_scenarios=20/20")
print(
    "bridge_soak="
    f"{soak_summary['scheduler_events_completed']} scheduler events, "
    f"{soak_summary['action_lifecycles_completed']} action lifecycles, "
    f"{soak_summary['save_load_cycles_completed']} save/load cycles"
)
print(f"bridge_soak_elapsed_ms={soak_summary['elapsed_ms']}")
PY
