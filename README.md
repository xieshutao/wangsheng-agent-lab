# WangSheng Agent Lab

Reliability-first framework for AI-controlled game NPCs.

Version 0.4.3 is a trace-driven repair release built from the frozen v0.4.2 DeepSeek 20-Episode run. The official v0.4.2 result remains 7/20 (35%); v0.4.3 does not rewrite or rerun that evidence.

The model remains an action proposer. World truth, permissions, hard constraints, action execution, report grounding, memory access and task completion remain deterministic.

## v0.4.3 milestone

- model-facing `report` accepts stable `fact_ids` from `world.reportable_facts`
- runtime still accepts legacy structured facts for deterministic regression only
- `ask_through.topic` is a frozen enum: `identity`, `purpose`, `request`, `door_state`
- topic-specific simulator evidence replaces the old identity-only response
- `completion_progress` exposes non-secret remaining requirements and accepted fact IDs
- conflict completion is derived from preserved claims instead of a hidden third field
- recent observations are bounded to three detailed results with a deterministic older-history summary
- loop detection uses semantic actions and evidence/world progress rather than free-text equality
- failed Executor results include retryability and required-change guidance
- malformed provider tool arguments retain a bounded diagnostic excerpt and parse position
- five frozen holdout scenarios are separated from the original 20 regression scenarios

The eight tools remain:

`move_to`, `observe`, `listen_at`, `ask_through`, `open`, `close`, `report`, `wait`

## Deterministic verification

```bash
python -m pip install -e ".[dev]"
scripts/verify_v043.sh
```

Expected verification:

```text
104 tests passed
20/20 original deterministic scenarios
5/5 frozen v0.4.3 holdout scenarios
0 executed hard violations
0 incomplete traces
Golden Trace passed / records_match / digest_match
```

## Runtime boundary

```text
ModelVisibleWorld
+ reportable_facts
+ current_affordances
+ completion_progress
+ compact history
→ exactly one native tool call
→ alias resolution
→ Tool Schema / Gateway
→ Executor
→ structured ActionResult
→ Evaluator
```

## Evidence limits

v0.4.3 is not production-ready and is not yet a real-model result. It must first be applied to the exact frozen v0.4.2 commit and pass deterministic verification. Only then may a new one-shot cloud blind test be designed. Do not rerun v0.4.2 or compare scores before reviewing the v0.4.3 experiment protocol.

See:

- `docs/V0.4.2_TRACE_AUDIT.md`
- `docs/CLOUD_EPISODE_SPEC_V0.4.3.md`
- `docs/HERMES_V0.4.3_APPLY_AND_VERIFY.md`
