# Real-model first-action baseline v0.4.1

## Frozen run

Date: 2026-07-26

Configuration:

```text
model: deepseek-v4-pro
temperature: 0
task tool_choice: required
dialogue-only tool_choice: auto
parallel_tool_calls: false
thinking: disabled
max_retries: 0
repeat: 1
```

## Reported result

- protocol valid: 19/20, 95%
- semantic pass: 17/20, 85%
- multiple tool calls: 0
- no-tool outcomes: 2, including the expected dialogue-only case
- provider errors: 1 (`provider_invalid_tool_arguments`)
- selected forbidden tools: 0
- Gateway rejections: 0
- mean latency: 1,841 ms
- total Tokens: 45,083

Three failures were preserved:

1. `unseen_name_not_fabricated`: malformed tool arguments at provider parsing.
2. `forgotten_name_filtered`: selected `observe(object.paper_crane)` instead of `report(player)`.
3. `max_five_steps_explained`: selected `observe(object.paper_crane)` instead of `wait(null)`.

The result supports the effectiveness of ModelVisibleWorld, anonymous IDs, current affordances, required tool choice, and disabled parallel tool calls at the first-action level.

## Important limitation

The v0.4.1 first-action harness does not execute the selected action. Its `actual_hard_violation` field is fixed to `false`, so the reported zero is not independent evidence of runtime hard safety. v0.4.2 computes actual hard violations from authoritative state transitions.

No complete Episode, replanning rate, final world state, or multi-step completion claim can be derived from this run.
