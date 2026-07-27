# WangSheng Headless Game Bridge v0.6 Status

**Implementation status:** FROZEN at commit `171807342291f7e5d7d2d89ae125a523b22ff032`
**Parent SPEC commit:** `4aaf1bd1ed6f17fd72f0ebcbfe2e1db10b8bb816`
**Target version:** `0.6.0`

## Implemented

- strict canonical protocol envelope and structured error taxonomy;
- deterministic virtual clock and stable-priority scheduler;
- action lifecycle ledger with one terminal state, actor exclusivity and a bounded epoch-local terminal idempotency cache;
- bounded message/action idempotency windows and conflict detection;
- stale epoch/version/task-generation rejection;
- minimal authoritative front-hall world;
- asynchronous movement, observation, listening, questioning, reporting and waiting;
- mid-action path/visitor interruption;
- pause/resume, cancellation, deadlines and provider-outage events;
- canonical snapshots, ordered deltas and digest replay;
- save/load with active-action continuation, epoch invalidation and terminal-cache reset;
- in-memory and JSONL trace/replay transports;
- detached adapter to existing Gateway and NPC Core world representation;
- 20 deterministic bridge scenarios;
- bounded recent report/heard-event histories;
- accelerated 10,000-event / 10,000-single-world-action / 100-save-load soak runner.

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

Rerun the Qwen3-4B 20-scenario + 30-minute model-in-the-loop acceptance against the bounded-state commit, audit the private archive, then freeze v0.6. The memory-versioning v0.7 milestone follows after freeze.
