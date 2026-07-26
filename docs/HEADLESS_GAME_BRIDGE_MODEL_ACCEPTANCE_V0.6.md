# WangSheng v0.6 Model-in-the-loop Headless Acceptance

Status: implementation candidate

Frozen implementation baseline:

- branch: `feat/headless-game-bridge-v0.6`
- commit: `c9cb0e0ac02012128862e6c01d879b67b137fd6a`
- bridge protocol: `0.6`
- candidate model: Qwen3-4B Q5_K_M
- runtime: llama.cpp b9637 / aedb2a5

## Purpose

This acceptance phase verifies that a real local model can drive the asynchronous v0.6 bridge without gaining authority over world state. It is separate from the v0.5.1 text-world benchmark and does not replace the frozen 30-Episode result.

The model still proposes one immediate action. `Gateway` validates the action. `HeadlessGameWorld` is the sole physical-state writer. Bridge messages and world versions are authoritative.

## Frozen evaluation sets

The catalog contains 20 one-run scenarios:

| Set | Count | Coverage |
|---|---:|---|
| Basic asynchronous tasks | 8 | move, ask, observe, listen, report and deterministic renderer |
| Fault recovery | 8 | stale version, path interruption, target departure, cancel, pause, expiry, provider timeout, duplicate request |
| Save/load and isolation | 4 | duplicate completion, active-action load, dialogue isolation, provider recovery |

The scenario directory is `scenarios_bridge_model_v060/`. Scenario content must not change after the implementation commit used for the formal run.

## Formal 20-scenario gates

Infrastructure gates are absolute:

- duplicate world mutation = 0
- invalid lifecycle transition = 0
- stale response applied = 0
- mutation after cancellation = 0
- save/load digest mismatch = 0
- incomplete trace = 0
- hard violation = 0
- provider failure corrupting world = 0

Model gates:

- passed scenarios >= 16/20
- protocol valid rate >= 95%
- grounded rate >= 90%
- hallucinated target count = 0
- knowledge violation count = 0

A model behavior miss does not invalidate the bridge if every infrastructure gate remains zero. An infrastructure violation blocks v0.6 freeze regardless of task pass rate.

## Thirty-minute real-model soak

The soak is wall-clock based and defaults to 1,800 seconds. Faults are assigned to collision-free decision slots:

- 20 player cancellations
- 20 external world changes
- 10 pause/resume cycles
- 10 save/load cycles
- 5 simulated provider timeouts

Required result:

- all scheduled faults injected exactly once
- no stale or duplicate world mutation
- no post-cancel mutation
- no save/load digest mismatch
- no hard violation
- no provider failure corrupting world

The soak measures world integrity. It is not a replacement benchmark for NPC intelligence.

## Output policy

Formal output must be outside the public Git repository. The runner writes:

- preflight and provider configuration
- hardware manifest and telemetry
- synthetic tool contract before and after the run
- per-scenario model trace
- per-scenario bridge JSONL trace
- reports, summary and checksums

Raw traces remain private. The public repository may contain only a sanitized report and the archive SHA-256.

## Commands

Formal scenario run:

```bash
python tools/run_bridge_model_acceptance.py \
  --project-root . \
  --scenario-dir scenarios_bridge_model_v060 \
  --output-dir /private/path/v060-model-acceptance \
  --base-url http://127.0.0.1:8080/v1 \
  --model qwen3-4b-q5km \
  --server-pid "$LLAMA_SERVER_PID"
```

Thirty-minute soak:

```bash
python tools/run_bridge_model_soak.py \
  --project-root . \
  --output-dir /private/path/v060-model-soak \
  --base-url http://127.0.0.1:8080/v1 \
  --model qwen3-4b-q5km \
  --duration-seconds 1800 \
  --decision-interval-seconds 2
```

## Non-goals

This phase does not add UE5, multi-NPC simulation, inventory, combat, long-term memory, the 留名簿 system or model training. It does not modify the v0.5.1 prompt, tool schemas, Gateway, evaluator or frozen benchmark results.
