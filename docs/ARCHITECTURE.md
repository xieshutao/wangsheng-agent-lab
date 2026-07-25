# Architecture

## Non-negotiable rule

The model proposes one action. It never decides whether the action succeeded,
whether a target exists, or whether the task is complete.

## Model boundary

`ModelPolicy` performs exactly one provider request per engine tick.

The provider returns raw text. `StrictActionParser` accepts only one JSON
object with these fields:

- `name`: required non-empty string
- `target`: string or null
- `parameters`: object

No Markdown, prose, arrays, extra top-level fields, or malformed types are
accepted.

## Error handling

Parser and provider failures become structured observations. They consume one
tick, do not mutate the world, and are included in the next policy context.

## Provider interface

`TextProvider.complete(prompt) -> str`

Included implementations:

- `ScriptedTextProvider`: deterministic tests
- `OpenAICompatibleProvider`: vLLM, llama.cpp server, Ollama-compatible
  endpoints, or cloud APIs

## Existing control loop

Player command
-> persistent ActiveTask
-> one provider call
-> one strict Action
-> Gateway
-> Executor
-> Observation
-> Evaluator
-> next tick
