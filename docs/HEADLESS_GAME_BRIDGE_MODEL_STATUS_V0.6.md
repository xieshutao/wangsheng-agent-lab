# v0.6 Model-in-the-loop Acceptance Status

Implementation status: pre-freeze bounded-state fix implemented; replacement formal model run not yet executed.

## Added components

- `src/wangsheng/bridge/model_acceptance.py`
- 20 frozen model-in-the-loop bridge scenarios
- formal local runner with pre/post tool contract and telemetry
- wall-clock 30-minute soak runner
- deterministic adaptive-provider tests
- report fact-ID validation at the bridge adapter boundary
- report evidence reconstruction for the existing evaluator

## Offline acceptance

- pre-fix complete pytest suite: 154 passed
- bounded-state fix suite: 159 passed
- reference model paths: 20/20
- short fault-injected soak: passed
- original v0.6 bridge scenarios and soak remain covered by the full suite

## Pre-freeze audit result

The first formal 20-scenario and 30-minute run passed behaviorally, but audit found unbounded terminal-action and report histories plus incomplete shell-runner provenance. Its archive remains valid pre-fix capability evidence, not final freeze evidence. See `V0.6_PRE_FREEZE_AUDIT_AND_BOUNDED_STATE_FIX.md`.

## Required next action

Commit and verify the bounded-state patch, then generate a new Hengyuan RTX 4090 runner fixed to that exact commit. The replacement runner must archive its own source, full preflight logs, Git evidence and formal lock. Rerun 20 scenarios plus the 30-minute soak once; do not merge `main` or tag `v0.6` until the replacement archive passes independent audit.
