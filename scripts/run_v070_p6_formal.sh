#!/usr/bin/env bash
set -euo pipefail

: "${WANGSHENG_PYTHON:?Set WANGSHENG_PYTHON to the repository venv Python absolute path}"
: "${WANGSHENG_P6_OUTPUT:?Set WANGSHENG_P6_OUTPUT to a fresh private path outside the repository}"
: "${WANGSHENG_MODEL_ALIAS:=qwen3-4b-q5km}"
: "${WANGSHENG_BASE_URL:=http://127.0.0.1:8080/v1}"

if [[ "$(git rev-parse --abbrev-ref HEAD)" != "eval/v0.7-p6-real-model" ]]; then
  echo "ERROR: formal P6 must run from eval/v0.7-p6-real-model" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree must be clean before the formal P6 run" >&2
  git status --short >&2
  exit 2
fi
if [[ -e "$WANGSHENG_P6_OUTPUT" ]] && [[ -n "$(find "$WANGSHENG_P6_OUTPUT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "ERROR: WANGSHENG_P6_OUTPUT must be absent or empty" >&2
  exit 2
fi

export PYTHONPATH=src
"$WANGSHENG_PYTHON" -m compileall -q src/wangsheng/memory scripts tools tests/memory
"$WANGSHENG_PYTHON" scripts/verify_v070_p5.py
"$WANGSHENG_PYTHON" scripts/verify_v070_p6.py
"$WANGSHENG_PYTHON" -m pytest tests/memory -q
"$WANGSHENG_PYTHON" -m pytest -q
git diff --check

args=(
  tools/run_v070_model_acceptance.py
  --project-root .
  --scenario-dir scenarios_memory_model_v070
  --output-dir "$WANGSHENG_P6_OUTPUT"
  --base-url "$WANGSHENG_BASE_URL"
  --model "$WANGSHENG_MODEL_ALIAS"
  --timeout 60
  --max-tokens 192
)
if [[ -n "${WANGSHENG_SERVER_PID:-}" ]]; then
  args+=(--server-pid "$WANGSHENG_SERVER_PID")
fi

"$WANGSHENG_PYTHON" "${args[@]}"
sha256sum "$WANGSHENG_P6_OUTPUT/summary.json" "$WANGSHENG_P6_OUTPUT/SHA256SUMS.txt"
