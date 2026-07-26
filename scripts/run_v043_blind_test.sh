#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ---- Ensure python is on PATH (use venv from any known location) ----
if [ -d "/tmp/tmp.d3o4fbnBeT/wangsheng-agent-lab/.venv" ]; then
  VENV_PYTHON="/tmp/tmp.d3o4fbnBeT/wangsheng-agent-lab/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  VENV_PYTHON="python3"
else
  VENV_PYTHON="/root/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11"
fi
PYTHON_CMD="$VENV_PYTHON"
export PYTHON_CMD

# ---- Source API key from Hermes env file ----
if [ -z "${WANGSHENG_CLOUD_API_KEY:-}" ]; then
  HERMES_ENV="/root/.hermes/.env"
  if [ -f "$HERMES_ENV" ]; then
    set -a
    source "$HERMES_ENV"
    set +a
    WANGSHENG_CLOUD_API_KEY="${DEEPSEEK_API_KEY:-}"
  fi
fi
export WANGSHENG_CLOUD_API_KEY
if [ -z "${WANGSHENG_CLOUD_API_KEY:-}" ]; then
  echo "WANGSHENG_CLOUD_API_KEY is not set; stopping."
  exit 10
fi

EXPECTED_COMMIT="3dc5ac5f85135c6f2e66c6f34d78d2225bd80ecb"
ACTUAL_COMMIT="$(git rev-parse HEAD)"
if [ "$ACTUAL_COMMIT" != "$EXPECTED_COMMIT" ]; then
  echo "Commit mismatch; expected $EXPECTED_COMMIT got $ACTUAL_COMMIT"
  exit 21
fi

$PYTHON_CMD -c "import wangsheng; assert wangsheng.__version__ == '0.4.3', f'expected 0.4.3, got {wangsheng.__version__}'"

# ---- Output paths ----
REGRESSION_DIR="/tmp/wangsheng-v043-deepseek-regression"
HOLDOUT_DIR="/tmp/wangsheng-v043-deepseek-holdout"
CONSOLE_LOG="/tmp/wangsheng-v043-deepseek-25episodes-console.txt"

if [ -e "$REGRESSION_DIR" ] || [ -e "$HOLDOUT_DIR" ] || [ -e "$CONSOLE_LOG" ]; then
  echo "Output path already exists; refusing to overwrite."
  echo "  Regression: $REGRESSION_DIR"
  echo "  Holdout: $HOLDOUT_DIR"
  echo "  Console: $CONSOLE_LOG"
  echo "Remove manually if needed."
  exit 30
fi

DEEPSEEK_ARGS=(
  --base-url "https://api.deepseek.com"
  --model "deepseek-v4-pro"
  --tool-choice required
  --temperature 0
  --top-p 1
  --max-tokens 256
  --timeout 120
  --max-retries 0
  --retry-backoff 0
  --send-parallel-tool-calls
  --extra-body-json '{"thinking":{"type":"disabled"}}'
)

# ========================
#  RUN 1: REGRESSION (20)
# ========================
echo "===== [1/2] REGRESSION: 20 scenarios ====="
$PYTHON_CMD -m wangsheng.cli run-cloud-episodes \
  "${DEEPSEEK_ARGS[@]}" \
  --scenario-dir scenarios \
  --output-dir "$REGRESSION_DIR" \
  2>&1

echo "===== REGRESSION DONE ====="

# ========================
#  RUN 2: HOLDOUT (5)
# ========================
echo "===== [2/2] HOLDOUT: 5 scenarios ====="
$PYTHON_CMD -m wangsheng.cli run-cloud-episodes \
  "${DEEPSEEK_ARGS[@]}" \
  --scenario-dir scenarios_v043_holdout \
  --output-dir "$HOLDOUT_DIR" \
  2>&1

echo "===== HOLDOUT DONE ====="

# Collect console output to a single log
{
  echo "===== V0.4.3 DEEPSEEK 25-EPISODE BLIND TEST ====="
  echo "Commit: $ACTUAL_COMMIT"
  echo "Timestamp: $(date --iso-8601=seconds)"
  echo ""
  echo "--- REGRESSION SUMMARY ---"
  if [ -f "$REGRESSION_DIR/summary.json" ]; then
    $PYTHON_CMD -m json.tool "$REGRESSION_DIR/summary.json"
  fi
  echo ""
  echo "--- HOLDOUT SUMMARY ---"
  if [ -f "$HOLDOUT_DIR/summary.json" ]; then
    $PYTHON_CMD -m json.tool "$HOLDOUT_DIR/summary.json"
  fi
  echo ""
  echo "--- AGGREGATED RESULTS ---"
  $PYTHON_CMD -c "
import json, sys
from pathlib import Path

def load_summary(path):
    s = json.loads(Path(path).read_text())
    return {
        'episode_count': s.get('episode_count', 0),
        'scenario_count': s.get('scenario_count', 0),
        'passed': s.get('passed', 0),
        'failed': s.get('failed', 0),
        'passed_rate': s.get('passed_rate', 0),
        'protocol_valid_rate': s.get('protocol_valid_rate', 0),
        'grounded_rate': s.get('grounded_rate', 0),
        'hard_violation_count': s.get('actual_hard_violation_count', 0),
        'hallucinated_target_count': s.get('hallucinated_target_count', 0),
        'loop_count': s.get('loop_count', 0),
        'max_steps_count': s.get('max_steps_count', 0),
        'total_tokens': s.get('total_tokens', 0),
        'provider_error_count': s.get('provider_error_count', 0),
        'mean_steps': s.get('mean_steps', 0),
        'mean_total_tokens': s.get('mean_total_tokens', 0),
    }

reg = load_summary('$REGRESSION_DIR/summary.json')
hol = load_summary('$HOLDOUT_DIR/summary.json')

print('REGRESSION (20):')
for k, v in reg.items():
    print(f'  {k}: {v}')

print()
print('HOLDOUT (5):')
for k, v in hol.items():
    print(f'  {k}: {v}')

print()
total_passed = reg['passed'] + hol['passed']
total_count = reg['episode_count'] + hol['episode_count']
print(f'OVERALL: {total_passed}/{total_count} = {total_passed/total_count*100:.1f}%')
print(f'  Regression: {reg[\"passed\"]}/{reg[\"episode_count\"]} ({reg[\"passed_rate\"]*100:.1f}%)')
print(f'  Holdout:    {hol[\"passed\"]}/{hol[\"episode_count\"]} ({hol[\"passed_rate\"]*100:.1f}%)')
print(f'  Total hard violations: {reg[\"hard_violation_count\"] + hol[\"hard_violation_count\"]}')
print(f'  Total hallucinated targets: {reg[\"hallucinated_target_count\"] + hol[\"hallucinated_target_count\"]}')
print(f'  Total loops: {reg[\"loop_count\"] + hol[\"loop_count\"]}')
print(f'  Total max_steps: {reg[\"max_steps_count\"] + hol[\"max_steps_count\"]}')
total_tok = reg['total_tokens'] + hol['total_tokens']
print(f'  Total tokens: {total_tok}')
print(f'  Mean tokens/episode: {total_tok/total_count:.0f}')
"
} | tee "$CONSOLE_LOG"

# Package results
PACKAGE="/tmp/wangsheng-v043-deepseek-results.tar.gz"
tar czf "$PACKAGE" -C /tmp \
  "wangsheng-v043-deepseek-regression" \
  "wangsheng-v043-deepseek-holdout" \
  2>/dev/null || true

echo ""
echo "===== ALL DONE ====="
echo "Regression output: $REGRESSION_DIR"
echo "Holdout output:    $HOLDOUT_DIR"
echo "Console log:       $CONSOLE_LOG"
echo "Package:           $PACKAGE"
