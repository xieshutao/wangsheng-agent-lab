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

# Remove ignored bytecode from the checked-out source tree. This does not alter
# tracked files and prevents a copied workspace from retaining stale imports.
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

root = Path.cwd().resolve()
module = Path(wangsheng.__file__).resolve()
if root not in module.parents:
    raise SystemExit(
        f"wangsheng import is not from the current worktree: module={module} root={root}"
    )
if wangsheng.__version__ != "0.5.1":
    raise SystemExit(f"unexpected version: {wangsheng.__version__}")
print(f"python={Path(sys.executable).resolve()}")
print(f"wangsheng_module={module}")
print("version=0.5.1")
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
