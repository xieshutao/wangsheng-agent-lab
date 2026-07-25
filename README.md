# WangSheng Agent Lab

Reliability-first framework for game NPC agents.

Version 0.3 freezes the deterministic text-runtime milestone before any real model or Unreal integration.

## v0.3 milestone

- 8 registered tools with strict schemas, permissions, timeout and cancellation metadata
- stable object IDs such as `door.front` and `visitor.xiaoman`
- ordered Action Gateway validation with explicit reason codes
- deterministic executor with authoritative state feedback
- loop detection and task cancellation
- 10 data-driven scripted scenarios
- JSONL per-step Trace with world-before, world-after and state delta
- batch `run_all` report with pass rate, hard violations and trace completeness

The eight tools are:

`move_to`, `observe`, `listen_at`, `ask_through`, `open`, `close`, `report`, `wait`

## Install and test

```bash
python -m pip install -e ".[dev]"
pytest -q
python -m wangsheng.cli run-all-scripted --scenario-dir scenarios --output-dir artifacts/scripted
```

Expected scripted milestone:

```text
10 scenarios
100% pass
0 executed hard violations
0 incomplete traces
```

## Important boundary

The strict text JSON model adapter from v0.2 remains only as a fallback contract test. Production cloud integration must use native function/tool calling in a later milestone.
