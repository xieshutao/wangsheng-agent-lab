# Cloud first-action experiment protocol v0.4.1

## Purpose

Measure P0 protocol validity and P1 immediate-action quality without mixing in multi-step completion.

## Frozen inputs

- 20 scenario files under `scenarios/`
- eight Tool Registry schemas
- first-action expectations under `experiments/`
- model-visible world schema v1
- prompt version `wangsheng.tool_call_prompt.v2`
- tool schema version `wangsheng.tool.v2`
- temperature 0 unless unsupported
- one named model and provider configuration per output directory

## Required provider configuration

Task cases:

```text
tool_choice=required
parallel_tool_calls=false
```

Chat-only cases:

```text
tool_choice=auto
```

The CLI uses these defaults. Disable transmission of `parallel_tool_calls` only when an endpoint rejects the field, and record that deviation.

## Run order

1. One-scenario smoke request.
2. Twenty scenarios once each (`20×1`).
3. Review protocol, Gateway and semantic failures.
4. Run a small fixed repeat set only after the one-pass results are understood.
5. Run `20×10` only if repeated statistics are still decision-relevant.

Never overwrite or selectively rerun failed cases into the same directory.

## Metrics

- protocol-valid rate
- semantic first-action rate
- model-visible target and resolved target
- no-tool and multi-tool counts
- selected forbidden tools
- Gateway rejection count and reason codes
- actual hard violations
- provider errors
- mean and p95 latency
- prompt, completion and total tokens

## Semantic rule

A task action is semantically passing only when:

1. exactly one valid native tool call is returned;
2. the selected tool and model-visible target match the frozen expectation;
3. Gateway allows the resolved action.

A chat-only case passes when no world-action tool is called.

## Evidence handling

Artifacts remain outside Git. Preserve the full directory and record source commit, exact model, base URL, prompt version, tool version and provider public configuration. Never store API keys.
