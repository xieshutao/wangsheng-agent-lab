# Cloud first-action experiment protocol

## Purpose

Measure P0 protocol validity and P1 first-action quality without mixing in multi-step execution or memory retrieval.

## Frozen inputs

- 20 scenario files under `scenarios/`
- eight tool schemas from `ToolRegistry`
- first-action expectations in `experiments/first_action_expectations.json`
- temperature 0 unless the provider cannot support it
- one named model and one provider configuration per result directory

## Run order

1. One-scenario smoke request.
2. Twenty scenarios once each (`20×1`).
3. Review endpoint compatibility and result completeness.
4. Twenty scenarios ten times each (`20×10`).

Do not selectively rerun failed cases into the same result directory.

## Metrics

- protocol-valid rate: exactly one native tool call for task cases, no world-action tool call for the chat-only case, and arguments pass Tool Schema
- semantic first-action rate: selected tool and target belong to the frozen acceptable set
- selected forbidden tools
- Gateway rejection count and reason codes
- actual hard violations, which must remain zero
- provider errors
- mean and p95 request latency
- prompt, completion and total tokens

## Evidence handling

Generated artifacts are ignored by Git. Keep the result directory intact and record the model name, provider base URL, prompt version, tool version and source commit. Never store API keys in result files.
