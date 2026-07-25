# WangSheng Agent Lab

Reliability-first framework for game NPC agents.

Version 0.3.1 closes the deterministic protocol gate before any real model or Unreal integration.

## v0.3.1 milestone

- 8 frozen tools with strict schemas, permissions, timeout, cancellation and memory metadata
- versioned `Intent`, `ActionRequest`, `ActionResult`, `MemoryEvent` and Trace contracts
- stable object IDs such as `door.front` and `visitor.xiaoman`
- ordered Action Gateway validation with explicit reason codes
- deterministic executor with authoritative state feedback and injected failure results
- minimal memory access filtering for `FORGOTTEN`, `SEALED` and `SUPPRESSED`
- loop detection, cancellation, post-terminal protection and max-step termination
- 20 data-driven scripted scenarios matching the current Core gate
- all scripted actions pass through the same strict parser and Gateway used by model-contract tests
- JSONL per-step Trace with context hash, action request/result, state delta and memory events
- normalized Golden Trace replay that ignores only timestamp and duration fields
- batch failure classification instead of a single undifferentiated pass/fail number

The eight tools remain:

`move_to`, `observe`, `listen_at`, `ask_through`, `open`, `close`, `report`, `wait`

## Install and test

```bash
python -m pip install -e ".[dev]"
pytest -q
python -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios \
  --output-dir artifacts/scripted
python tools/replay_trace.py \
  golden_traces/normal_observe_and_report.json
```

Expected deterministic gate:

```text
53 tests passed
20 scenarios
100% scenario pass
0 executed hard violations
0 incomplete traces
Golden Trace replay passed
```

## Important boundary

This version still does **not** prove that any real language model can plan correctly. The strict text JSON adapter remains a fallback contract test only. The next milestone must add one native function/tool-calling cloud adapter and run the same frozen scenarios without changing the Gateway, world rules or Evaluator.

The memory work in v0.3.1 is only a versioned access-control contract and deterministic test fixture. It is not the production save system, retrieval engine or full `留名簿` mechanic.
