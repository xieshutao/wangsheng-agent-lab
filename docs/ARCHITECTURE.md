# Architecture v0.4.1

## Runtime layers

1. Intent classifies player input as task, chat or refusal.
2. A task creates one persistent task state.
3. ContextBuilder produces actor-visible state and current affordances.
4. Policy requests at most one native model tool call per tick.
5. Model-visible target aliases are resolved to canonical world IDs.
6. Tool Registry validates argument Schema.
7. Action Gateway checks target, knowledge, permission, physical precondition and hard constraints.
8. Executor changes authoritative world state or returns a real failure code.
9. Evaluator decides completion from world evidence.
10. Trace records each layer, contract payload, state delta and model metadata.

## Two world representations

### FullWorldSnapshot

Used for:

- save/load
- deterministic replay
- Evaluator
- state diff
- debugging

It may contain canonical IDs, simulator queues and fields that must never be shown to a model.

### ModelVisibleWorld

Used only for model context. It contains:

- actor location and permissions
- known objects
- anonymous known entities
- accessible conversation facts
- accessible memories
- heard events and emotional residue

It excludes:

- raw visitor identity
- canonical IDs that encode hidden information
- sealed, forgotten or suppressed memories
- forced simulator results
- visitor response queues
- unobserved world objects

Model aliases are stable within the episode. For example:

```text
visitor.front_001 → internal visitor.xiaoman
```

The model sees only the left side. Resolution happens before Gateway validation.

## Authorization versus affordance

`authorized_actions` means the task permits a tool in principle.

`current_affordances` means whether the tool is executable in the current world state. It can expose:

- candidate model-visible targets
- `executable_now`
- `blocked_by`
- physical requirements
- required arguments such as a barrier ID

Affordances are advisory. Gateway remains authoritative and revalidates every action.

## Native tool-call boundary

The API receives standard tool objects containing only `type` and `function`. WangSheng-only metadata remains inside the runtime.

One tool call becomes one immediate action. Parallel future-plan calls are disallowed. Provider requests therefore default to:

```text
tool_choice=required
parallel_tool_calls=false
```

Dialogue-only scenarios use `tool_choice=auto` and may return no tool call.

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

The Gateway does not choose a substitute action.

## First-action experiment boundary

The first-action experiment asks for one turn and does not commit the action to world state. It records:

- native tool-call shape
- argument validity
- model-visible selected target
- resolved canonical target
- Gateway decision and reason code
- semantic first-action acceptance
- forbidden tool selection
- model latency and token usage

Semantic success requires both a frozen acceptable action and a Gateway-allowed result.

## Stable replay

The Golden Trace was intentionally regenerated because model context is now a different contract. The authoritative world and deterministic scenario outcome remain stable.

Current normalized digest:

```text
14282d3127cffb67f529db1f95e7cf552b3d3b406fbaf4fdf55014fe6587e944
```
