# v0.4.3 Cloud Episode Spec — Failure-Aware Replanning

**Version**: 0.4.3
**Branch**: `feat/failure-aware-replanning-v0.4.3`
**Commit**: `3dc5ac5f85135c6f2e66c6f34d78d2225bd80ecb`

## Changes from v0.4.2

### Report interface
- Model selects from deterministic `fact_ids` instead of generating predicate/source/certainty.
- Facts are pre-constructed by the system; model only chooses which to include.

### ask_through topic enum
- `topic` accepts only: `identity`, `purpose`, `request`, `door_state`.
- Different topics return different evidence (not always "name").

### Completion progress
- New `completion_progress` field tells model what facts remain and which are sufficient.
- Reduces unnecessary extra actions after objective is met.

### Context compression
- Only last 3 complete Observations retained in context.
- Older history collapsed into deterministic summaries.
- Target: ~50-70% token reduction.

### Semantic loop detection
- Previously: string-based action comparison (rephrasing bypassed detection).
- Now: semantic action comparison (rephrased report/question still detected as loop).
- Lock step count: same action 3+ consecutive → LOOP_DETECTED.

### Conflicting testimony
- No longer requires model to fabricate `identity_status=CONFLICTED`.
- Conflict is now a system-level evaluation, not model output.

### Provider error diagnostics
- Invalid JSON responses now record: first N chars of raw response + parse position.

## Run command

```bash
python -m wangsheng.cli run-cloud-episodes \
  --base-url https://api.deepseek.com \
  --model deepseek-v4-pro \
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
  --output-dir /tmp/wangsheng-v043-deepseek-regression
```

For holdout scenarios, replace `--scenario-dir scenarios` with `--scenario-dir scenarios_v043_holdout`.

## Results

See `V0.4.3_DEEPSEEK_BLIND_TEST.md` for full report.
