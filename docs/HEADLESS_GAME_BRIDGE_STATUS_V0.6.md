# WangSheng Headless Game Bridge v0.6 Status

**Implementation status:** deterministic reference implementation ready for frozen validation
**Parent SPEC commit:** `4aaf1bd1ed6f17fd72f0ebcbfe2e1db10b8bb816`
**Target version:** `0.6.0`

## Implemented

- strict canonical protocol envelope and structured error taxonomy;
- deterministic virtual clock and stable-priority scheduler;
- action lifecycle ledger with one terminal state and actor exclusivity;
- message/action idempotency and conflict detection;
- stale epoch/version/task-generation rejection;
- minimal authoritative front-hall world;
- asynchronous movement, observation, listening, questioning, reporting and waiting;
- mid-action path/visitor interruption;
- pause/resume, cancellation, deadlines and provider-outage events;
- canonical snapshots, ordered deltas and digest replay;
- save/load with active-action continuation and epoch invalidation;
- in-memory and JSONL trace/replay transports;
- detached adapter to existing Gateway and NPC Core world representation;
- 20 deterministic bridge scenarios;
- accelerated 10,000-event / 1,000-action / 100-save-load soak runner.

## Frozen compatibility boundary

The implementation does not change the v0.5.1 model prompt, existing tool schema, Gateway, Executor, Evaluator, deterministic renderer or the frozen Regression/Holdout scenarios. The Qwen3-4B v0.5.1 `27/30` result remains immutable.

## Deterministic acceptance commands

```bash
bash scripts/verify_v060.sh
```

The verification script checks:

- package version `0.6.0` and current-worktree import source;
- full pytest suite;
- frozen 20 + 5 + 5 scripted suites;
- exact v0.5.1 Golden Trace digest;
- 20/20 bridge scenarios;
- full accelerated soak gates.

## Out of scope

UE5, public networking, multiple controlled NPCs, combat, inventory, trading, long-term memory, the `留名簿` mechanic and model retraining remain out of scope for v0.6.

## Next milestone after acceptance

Implement a thin UE5 adapter that emits and consumes the same protocol without changing the bridge or model-facing contracts.
