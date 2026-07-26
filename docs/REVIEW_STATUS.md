# Current Review Status

**Version**: 0.4.3

## Complete

- deterministic runtime and authoritative executor
- persistent task and one-action ticks
- eight frozen tool schemas
- versioned Intent, ActionRequest, ActionResult, MemoryEvent and Trace contracts
- explicit reason codes and categorized failures
- gateway permissions, target checks, preconditions and hard constraints
- twenty original scenarios + five frozen holdout scenarios
- strict parser used by scripted scenario actions
- minimal forgetting, emotional residue, conflict and rewrite access tests
- loop detection, cancellation, terminal protection and max-step failure
- JSONL traces, state diffs, context hashes and Golden Trace replay
- batch summary metrics and failure classification
- OpenAI-compatible native tool-calling cloud provider
- failure-aware replanning contracts (fact IDs, topic enum, completion progress)
- context compression (last 3 Observations only, older history → deterministic summary)
- semantic loop detection (action content changes no longer bypass detection)
- provider error diagnostics (trimmed parameter fragments + parse position)
- **DeepSeek v4 Pro 25-Episode blind test**: 23/25 (92%) — regression 90%, holdout 100%
- **Token cost reduction**: 67.8% vs v0.4.2
- **Zero hard violations, zero hallucinated targets, zero loops, zero knowledge violations**

## Test classification (post-v0.4.3)

Two test categories separated:

1. **Runtime Regression** — Mock/Scripted Policy. Tests infrastructure: Gateway, Executor, Evaluator, Trace, loop detection, constraint enforcement. These intentionally include failure paths (forbidden actions, missing targets, locked doors).
2. **Real Model Evaluation** — Cloud model only. Tests whether the model completes reasonable objectives while maintaining safety. These must NOT require the model to deliberately trigger errors.

## Next milestone

- **v0.5**: Local Model Baseline
  - llama.cpp + GGUF integration
  - 4-bit/5-bit quantized 7B-9B models
  - Same strict Tool Calling contract
  - Measure throughput, latency, memory, pass rate on RTX 4060

## Still excluded

- local 9B deployment (deferred to v0.5)
- Unreal Engine adapter
- production memory database and retrieval (memory store, scheduled forgetting, belief system)
- voice, LoRA and AIGC model environments
