# WangSheng Agent Lab v0.5.1 Reliability Patch

## Scope

v0.5.1 is a narrow reliability patch built from the frozen v0.5 local-model evidence. It does not alter scenario truth, Gateway authority, Executor world-write authority, or evaluator completion semantics.

## Problems addressed

1. A model could select a grounded `fact_id` but write player-visible text that expressed a different proposition.
2. Small models could see valid reportable facts without clearly distinguishing them from the exact fact type required by the active task.
3. After timeout, path failure, a non-completing report, or repeated movement, the next-action context did not expose a compact deterministic recovery signal.
4. Dialogue-only turns still exposed world-action tool schemas with `tool_choice=auto`, allowing an unnecessary world-action selection.

## Frozen changes

### Deterministic report rendering

The model-facing `report` schema accepts:

- `target_id`
- `fact_ids`
- optional `tone` enum: `neutral`, `gentle`, `formal`

It no longer accepts report text. The Executor resolves trusted facts and renders the factual sentence deterministically. Legacy scripted `facts + text` remain available only to deterministic regression fixtures.

### Completion progress v2

The context now exposes:

- `required_fact_types`
- `satisfied_fact_types`
- `missing_fact_types`
- `accepted_fact_ids`
- `evidence_action_hints`
- `report_would_complete`
- `recovery_guidance`

The hints disclose task contract and action-to-evidence relationships, not hidden world answers.

### Evidence-aware affordances

`ask_through` advertises topic-to-evidence mappings and recommended topics for the active task. `report` is advisory-blocked when no task-completing fact is currently available.

### No-progress recovery guidance

The runtime identifies:

- successful reports that did not complete the task;
- A/B/A/B movement oscillation;
- three or more recent steps without new evidence;
- recovery after `TIMEOUT`, `NO_PATH`, `LOCKED`, or `TOO_FAR`.

The model receives actions to avoid and evidence-producing actions to prefer. Gateway and Executor remain authoritative.

### Tool-free dialogue routing

Dialogue-only requests use a separate prompt and send no world-action schemas. Action-like prose cannot mutate the world because no tool call is available for execution.

## Non-goals

- no model fine-tuning;
- no scenario or evaluator relaxation;
- no direct UE5 integration;
- no multi-NPC memory system;
- no claim that cloud RTX 4090 results validate RTX 4060 coexistence.

## Verification

- automated tests;
- original 20 scripted scenarios;
- frozen v0.4.3 holdout 5 scenarios;
- exact v0.5.1 Golden Trace replay;
- zero hard violations and zero incomplete traces in deterministic verification.
