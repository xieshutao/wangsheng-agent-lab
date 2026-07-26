# v0.6 Model-in-the-loop Acceptance Status

Implementation status: ready for deterministic review; no real model called during code generation.

## Added components

- `src/wangsheng/bridge/model_acceptance.py`
- 20 frozen model-in-the-loop bridge scenarios
- formal local runner with pre/post tool contract and telemetry
- wall-clock 30-minute soak runner
- deterministic adaptive-provider tests
- report fact-ID validation at the bridge adapter boundary
- report evidence reconstruction for the existing evaluator

## Offline acceptance

- complete pytest suite: 154 passed
- reference model paths: 20/20
- short fault-injected soak: passed
- original v0.6 bridge scenarios and soak remain covered by the full suite

## Required next action

Apply this implementation to the exact v0.6 implementation commit, run deterministic acceptance, commit and push an implementation branch. Only after the resulting commit is frozen should the Hengyuan RTX 4090 formal package be generated and executed.
