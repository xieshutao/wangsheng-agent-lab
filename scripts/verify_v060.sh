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
  --action-lifecycles 10000 \
  --save-load-cycles 100 \
  --terminal-action-cache-limit 256 \
  --request-cache-limit 512 \
  --report-history-limit 32 \
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
required = {
    "scheduler_events_completed": 10000,
    "action_lifecycles_completed": 10000,
    "save_load_cycles_completed": 100,
    "active_actions_final": 0,
    "terminal_cache_clear_mismatches": 0,
}
for key, expected in required.items():
    if soak_summary.get(key) != expected:
        raise SystemExit(f"bridge soak {key} mismatch: {soak_summary}")
if soak_summary["max_active_actions"] > 1:
    raise SystemExit(f"bridge active action bound failed: {soak_summary}")
if soak_summary["max_terminal_action_cache"] > soak_summary["terminal_action_cache_limit"]:
    raise SystemExit(f"bridge terminal cache bound failed: {soak_summary}")
if soak_summary["max_request_cache"] > soak_summary["request_cache_limit"]:
    raise SystemExit(f"bridge request cache bound failed: {soak_summary}")
if soak_summary["max_report_history"] > soak_summary["report_history_limit"]:
    raise SystemExit(f"bridge report history bound failed: {soak_summary}")
if soak_summary["max_save_bytes"] > 131072:
    raise SystemExit(f"bridge save size bound failed: {soak_summary}")
print("bridge_scenarios=20/20")
print(
    "bridge_soak="
    f"{soak_summary['scheduler_events_completed']} scheduler events, "
    f"{soak_summary['action_lifecycles_completed']} single-world action lifecycles, "
    f"{soak_summary['save_load_cycles_completed']} save/load cycles"
)
print(
    "bridge_live_bounds="
    f"active<={soak_summary['max_active_actions']}, "
    f"terminal={soak_summary['max_terminal_action_cache']}/{soak_summary['terminal_action_cache_limit']}, "
    f"requests={soak_summary['max_request_cache']}/{soak_summary['request_cache_limit']}, "
    f"reports={soak_summary['max_report_history']}/{soak_summary['report_history_limit']}, "
    f"max_save_bytes={soak_summary['max_save_bytes']}"
)
print(f"bridge_soak_elapsed_ms={soak_summary['elapsed_ms']}")
PY
