# WangSheng Agent Lab baseline status

## Current source candidate

- Version: `v0.4.2`
- Base source: `v0.4.1` ModelVisibleWorld / Action Affordances
- Runtime: Python 3.10+
- Runtime third-party dependencies: none
- Development dependencies: pytest and ruff

## Verified local scope

- 94 automated tests
- 20/20 deterministic scripted scenarios
- native multi-step fixture coverage for all 20 scenarios
- zero executed hard violations in deterministic regression
- zero incomplete traces
- Golden Trace replay remains covered
- first-action and old demos remain regression-tested

## v0.4.1 real-model evidence

The frozen DeepSeek V4 Pro `20×1` first-action run reported:

- protocol valid: 19/20, 95%
- semantic pass: 17/20, 85%
- multiple tool calls: 0
- provider errors: 1 malformed tool-argument response
- selected forbidden tools: 0
- Gateway rejections: 0
- mean latency: 1,841 ms
- total Tokens: 45,083

This is a first-action result only. It does not prove multi-step completion or replanning.

## What v0.4.2 adds

- `run-cloud-episodes`
- one native model call per active Tick
- Executor result feedback into the next model-visible context
- frozen scenario event injection
- provider/policy error fail-fast behavior for formal runs
- complete per-Tick sanitized request/response evidence
- real authoritative hard-violation detection
- episode pass, clean pass, objective completion, groundedness, target hallucination, replanning, Token, latency, and trace metrics
- dialogue-only no-world-action handling
- post-terminal verification without an extra model call
- code-level refusal to overwrite a non-empty result directory

## Current next gate

1. Apply v0.4.2 to a dedicated branch.
2. Verify exact source diff and run all 94 tests.
3. Run all 20 deterministic scripted scenarios and Golden Trace replay.
4. Commit and push the runner implementation only.
5. Use a fresh private output directory for one formal DeepSeek 20-Episode blind run.
6. Preserve all raw failures; do not rerun individual scenarios.
7. Analyze the result before changing Prompt, scenarios, tools, or expectations.

Do not merge to `main` before the implementation commit and formal result have been reviewed separately.
