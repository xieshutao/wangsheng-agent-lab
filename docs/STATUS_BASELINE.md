# WangSheng Agent Lab Baseline Status

## Frozen repository baseline

- Previous release: `v0.3.0`
- Verified previous runtime: 41 tests, 10/10 scripted scenarios, zero executed hard violations, zero incomplete traces
- Current candidate: `v0.3.1`
- Runtime language: Python 3.10+
- Runtime third-party dependencies: none
- Development dependencies: pytest and ruff

## What v0.3.1 adds

- Five versioned contracts: Intent, ActionRequest, ActionResult, MemoryEvent and TraceEvent
- Twenty deterministic Core scenarios
- Scripted scenario output routed through `StrictActionParser` and the normal Gateway
- Minimal memory visibility states for deterministic forgetting/rewrite tests
- Forced simulator failures for timeout/recovery tests
- Knowledge-grounded report validation
- Failure classification in `summary.json`
- Normalized Golden Trace and replay command
- Save/load world snapshot roundtrip test
- Post-terminal tick protection test

## Current verified scope

The code can determine whether a proposed action is structurally valid, allowed, executable and grounded in the simulated world. It can record exact state transitions and replay a known deterministic trajectory.

It cannot yet demonstrate:

- native cloud `tool_calls`
- real-model action quality
- token, latency or provider metadata
- production memory persistence/retrieval
- local 4B/9B deployment
- Unreal Engine execution
- voice, animation, LoRA or AIGC integration

## Gate decision

After v0.3.1 passes in the remote repository, the deterministic protocol gate is closed. Further deterministic framework expansion requires a failed real-model experiment that identifies a specific missing contract or evaluator defect.
