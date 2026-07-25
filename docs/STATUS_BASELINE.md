# WangSheng Agent Lab Baseline Status

## Frozen repository baseline

- Previous release: `v0.3.1`
- Verified deterministic runtime: 53 tests, 20/20 scripted scenarios, zero executed hard violations, zero incomplete traces, stable Golden Trace
- Current candidate: `v0.4.0`
- Runtime language: Python 3.10+
- Runtime third-party dependencies: none
- Development dependencies: pytest and ruff

## What v0.4.0 adds

- Native OpenAI-compatible `tool_calls` request and response handling
- Strict one-tool-call-per-tick policy
- Exact preservation of provider tool-call IDs
- Provider timeout, retry, redaction and public configuration reporting
- Model/token/latency metadata in Trace when a native provider is used
- Frozen first-action expectations for all 20 scenarios
- One-turn cloud smoke command
- 20×N experiment command with JSONL, CSV and aggregate metrics
- Explicit separation between protocol validity, semantic first-action quality and Gateway safety

## Current verified scope

The local source can deterministically validate the provider protocol and experiment calculations without external network access. It can send real native tool schemas to a configured OpenAI-compatible endpoint and record the resulting evidence.

The repository does not claim that a real model has passed until a named endpoint/model is run and the generated artifacts are reviewed.

## Gate decision

1. Run one smoke request.
2. Run the frozen 20×1 experiment.
3. If the endpoint shape is correct, run 20×10 without changing scenarios or expectations.
4. Only after P0/P1 results are frozen should the project implement full multi-step cloud-model replanning.

No additional deterministic scenarios should be added merely to improve a model score. A scenario or evaluator change requires a demonstrated contract defect independent of model quality.
