# WangSheng Agent Lab Baseline Status

## Repository baseline

- Previous deterministic release: `v0.3.1`
- Previous cloud harness candidate: `v0.4.0`
- Current candidate: `v0.4.1`
- Runtime language: Python 3.10+
- Runtime third-party dependencies: none
- Development dependencies: pytest and ruff

## Verified local scope

- 82 automated tests
- 20/20 deterministic scenarios
- zero executed hard violations
- zero incomplete traces
- Golden Trace replay passes
- old scripted and text-contract demos pass

## Real-model evidence that triggered v0.4.1

The first DeepSeek V4 Pro `20×1` run on `v0.4.0` produced:

- protocol valid: 11/20
- semantic pass: 5/20
- multiple tool calls: 7
- no tool calls: 3
- selected forbidden tools: 0
- actual hard violations: 0

A five-scenario configuration comparison then used:

```text
tool_choice=required
parallel_tool_calls=false
```

It produced:

- protocol valid: 5/5
- multiple tool calls: 0
- provider errors: 0
- semantic pass: 2/5

This separated transport/configuration defects from semantic/context defects.

## What v0.4.1 fixes

- correct one-action provider defaults
- hidden identity leakage through canonical target IDs
- confusion between authorized tools and executable actions
- missing physical prerequisite descriptions
- first-action semantic scoring that ignored Gateway rejection
- lack of explicit alias-to-canonical trace evidence

## Next gate

1. Apply and verify `v0.4.1`.
2. Run one smoke request with frozen configuration.
3. Run a new non-overwriting `20×1` experiment.
4. Compare with the original `v0.4.0` baseline.
5. If semantic failures are localized, implement the full multi-step loop and replanning test.

Do not change expectations after seeing model answers unless an independent world-contract defect is demonstrated and documented.
