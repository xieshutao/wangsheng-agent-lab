# Architecture v0.4.0

## Runtime layers

1. Intent classifies player input as task, chat or refusal.
2. A task creates one persistent task state.
3. Policy requests at most one native model tool call per tick.
4. Native provider response becomes an `Action`; ordinary prose is not parsed as an action.
5. Tool Registry validates the selected tool's argument schema.
6. Action Gateway checks target, knowledge, permission, precondition and hard constraints.
7. Executor changes authoritative world state or returns a real failure code.
8. Evaluator decides completion from world evidence.
9. Trace records each layer, contract payload, state delta and model metadata.

## Native tool-call boundary

The API receives standard tool objects containing only `type` and `function`. WangSheng-only metadata such as permission, timeout and memory effects remains inside the runtime.

A provider tool call such as `call_123` becomes the action ID. The same ID must appear in the subsequent `ActionRequest`, execution observation and `ActionResult`. This is required for later UE action-result correlation.

Multiple parallel tool calls are rejected by Policy because one runtime tick may execute at most one action. The Gateway never selects an alternative action.

## Gateway validation order

1. active task
2. registered tool
3. tool available to this task
4. argument schema
5. target existence
6. target knowledge
7. actor permission
8. physical precondition
9. hard task constraint

## First-action experiment boundary

The v0.4.0 experiment asks the model for one turn and does not execute the selected tool. It records:

- native tool-call shape
- argument Schema validity
- selected tool and target
- frozen semantic first-action acceptance
- Gateway decision and reason code
- forbidden tool selection
- model latency and token usage

`actual_hard_violation_count` remains zero because the experiment never commits an action to world state. Full execution and replanning belongs to the next milestone.

## Stable replay

The v0.3.1 Golden Trace remains unchanged. Model metadata is included only on native-model traces, so deterministic scripted replay continues to compare the same normalized records.
