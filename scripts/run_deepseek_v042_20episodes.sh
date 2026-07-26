#!/usr/bin/env bash
set -euo pipefail
set +x

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -z "${WANGSHENG_CLOUD_API_KEY:-}" ]; then
  echo "WANGSHENG_CLOUD_API_KEY is not set; stopping."
  exit 10
fi

if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  if [ -n "$(git status --short)" ]; then
    echo "Git worktree is not clean; stopping."
    git status --short
    exit 20
  fi
  if [ -n "${WANGSHENG_EXPECTED_COMMIT:-}" ]; then
    ACTUAL_COMMIT="$(git rev-parse HEAD)"
    if [ "$ACTUAL_COMMIT" != "$WANGSHENG_EXPECTED_COMMIT" ]; then
      echo "Commit mismatch; expected $WANGSHENG_EXPECTED_COMMIT got $ACTUAL_COMMIT"
      exit 21
    fi
  fi
fi

python - <<'PY'
import wangsheng
if wangsheng.__version__ != "0.4.2":
    raise SystemExit(f"expected wangsheng 0.4.2, got {wangsheng.__version__}")
PY

OUTPUT_DIR="${WANGSHENG_EPISODE_OUTPUT_DIR:-/tmp/wangsheng-v042-deepseek-20episodes}"
CONSOLE_LOG="${WANGSHENG_EPISODE_CONSOLE_LOG:-/tmp/wangsheng-v042-deepseek-20episodes-console.txt}"

if [ -e "$OUTPUT_DIR" ]; then
  echo "Output path already exists; refusing to overwrite: $OUTPUT_DIR"
  exit 30
fi
if [ -e "$CONSOLE_LOG" ]; then
  echo "Console log already exists; refusing to overwrite: $CONSOLE_LOG"
  exit 31
fi

python -m wangsheng.cli run-cloud-episodes \
  --base-url "https://api.deepseek.com" \
  --model "deepseek-v4-pro" \
  --tool-choice required \
  --temperature 0 \
  --top-p 1 \
  --max-tokens 256 \
  --timeout 120 \
  --max-retries 0 \
  --retry-backoff 0 \
  --send-parallel-tool-calls \
  --extra-body-json '{"thinking":{"type":"disabled"}}' \
  --scenario-dir scenarios \
  --output-dir "$OUTPUT_DIR" \
  2>&1 | tee "$CONSOLE_LOG"

python - "$OUTPUT_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
required = [
    root / "provider_config.json",
    root / "experiment_manifest.json",
    root / "results.jsonl",
    root / "results.csv",
    root / "summary.json",
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit(f"missing formal-run artifacts: {missing}")

summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
results = [
    json.loads(line)
    for line in (root / "results.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
if summary.get("episode_count") != 20 or summary.get("scenario_count") != 20:
    raise SystemExit(
        f"expected 20 episodes/20 scenarios, got "
        f"{summary.get('episode_count')}/{summary.get('scenario_count')}"
    )
if len(results) != 20:
    raise SystemExit(f"expected 20 result records, got {len(results)}")

print("===== SANITIZED SUMMARY =====")
print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
print("===== PER-EPISODE CORE RESULTS =====")
for item in results:
    print(json.dumps({
        "scenario_id": item.get("scenario_id"),
        "passed": item.get("passed"),
        "clean_pass": item.get("clean_pass"),
        "objective_completed": item.get("objective_completed"),
        "protocol_valid": item.get("protocol_valid"),
        "grounded": item.get("grounded"),
        "status": item.get("status"),
        "terminal_reason": item.get("terminal_reason"),
        "steps": item.get("steps"),
        "model_call_count": item.get("model_call_count"),
        "tool_call_count": item.get("tool_call_count"),
        "action_count": item.get("action_count"),
        "gateway_rejection_count": item.get("gateway_rejection_count"),
        "execution_failure_count": item.get("execution_failure_count"),
        "hallucinated_target_count": item.get("hallucinated_target_count"),
        "actual_hard_violation_count": item.get("actual_hard_violation_count"),
        "provider_error_count": item.get("provider_error_count"),
        "total_tokens": item.get("total_tokens"),
        "latency_ms": item.get("latency_ms"),
        "actions": item.get("actions"),
        "failures": item.get("failures"),
    }, ensure_ascii=False, sort_keys=True))
PY

if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  echo "===== GIT STATUS ====="
  git status --short
fi

echo "Formal 20-Episode run finished. Do not rerun failed scenarios."
