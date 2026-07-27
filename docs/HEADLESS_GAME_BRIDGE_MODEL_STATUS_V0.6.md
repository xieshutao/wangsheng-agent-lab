# v0.6 Model-in-the-loop Acceptance Status

Implementation status: **FROZEN** at commit `171807342291f7e5d7d2d89ae125a523b22ff032`.

Formal model-in-the-loop acceptance completed 2026-07-27. Archive SHA-256: `b0f60eecb0cd30f44a7c5caf1587de495d495068ac90a4c79031601280a31728`.

## Formal Qwen3-4B results

- 20 scenarios: **20/20 passed**
- 30-minute soak: **1800.003 seconds, 872 tasks, 65/65 faults, 0 violations**
- State boundedness: terminal cache 78/256, active actions max 1, save payload ~16 KB
- Post-soak contract: **5/5 passed**
- Hard violations / hallucinated targets / knowledge violations / protocol errors: **0**

See `V0.6_FORMAL_EXPERIMENT_REPORT.md` for full details.

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
