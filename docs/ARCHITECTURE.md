# Architecture v0.3

## Runtime layers

1. Scenario/Player command creates one persistent task.
2. Policy selects one action.
3. Tool Registry validates the selected tool's argument schema.
4. Action Gateway checks target, knowledge, permission, precondition and hard constraints.
5. Executor changes authoritative world state or returns a real failure code.
6. Evaluator decides completion from world evidence.
7. Trace records each layer and state delta.

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

## Stable protocol

All tools expose function-compatible JSON schemas. This milestone does not call a real model; it freezes the schemas and deterministic behavior first.
