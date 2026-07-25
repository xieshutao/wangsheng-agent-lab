# Architecture v0.3.1

## Runtime layers

1. Intent classifies player input as task, chat or refusal.
2. A task creates one persistent task state.
3. Policy selects exactly one action per tick.
4. Strict parser converts the policy payload into an Action.
5. Tool Registry validates the selected tool's argument schema.
6. Action Gateway checks target, knowledge, permission, precondition and hard constraints.
7. Executor changes authoritative world state or returns a real failure code.
8. Evaluator decides completion from world evidence.
9. Trace records each layer, contract payload and state delta.

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

The Gateway never chooses an alternative action.

## Contract boundary

The domain runtime owns world truth, permissions, task completion, memory access and execution. Model-specific adapters may translate native provider messages into `ActionRequest`, but they may not modify those domain rules.

`FORGOTTEN`, `SEALED` and `SUPPRESSED` memory content is removed in code before PolicyContext is built. Trace retains the authoritative memory record for auditing, while the model-facing context receives only accessible memories.

## Stable replay

Golden Trace comparison removes only nondeterministic timestamp and duration fields. Context hashes, actions, Gateway results, executor results, state deltas, task states and memory access behavior must match exactly.
