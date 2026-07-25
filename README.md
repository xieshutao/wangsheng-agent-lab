# WangSheng Agent Lab

Reliability-first framework for AI-controlled game NPCs.

Version 0.4.0 opens the real-model evaluation phase without changing the frozen v0.3.1 world rules, Gateway, Executor or deterministic scenarios.

## v0.4.0 milestone

- native OpenAI-compatible `tool_calls` provider
- exactly one tool call per active task tick
- ordinary assistant prose is never parsed into an action
- provider `tool_call_id` is preserved through `Action`, `ActionRequest`, `ActionResult` and Trace
- API-only tool schemas strip WangSheng internal metadata before transmission
- configurable timeout, bounded retry and retry backoff
- credential redaction in provider errors
- model, request, token, latency, finish reason and response-hash metadata
- frozen 20-scenario P0/P1 first-action experiment
- one dialogue-only case that correctly expects no world-action tool call
- JSONL, CSV and aggregate JSON experiment outputs
- forbidden tool selection is recorded but never executed during first-action evaluation
- deterministic v0.3.1 regression gate remains intact

The eight tools remain:

`move_to`, `observe`, `listen_at`, `ask_through`, `open`, `close`, `report`, `wait`

## Install and deterministic regression

```bash
python -m pip install -e ".[dev]"
pytest -q
python -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios \
  --output-dir artifacts/scripted
python tools/replay_trace.py \
  golden_traces/normal_observe_and_report.json
```

Expected local verification for this source release:

```text
73 tests passed
20/20 deterministic scenarios
0 executed hard violations
0 incomplete traces
Golden Trace replay passed
```

## Configure one cloud model

Copy `.env.example` values into the shell or a private environment file that is never committed:

```bash
export WANGSHENG_CLOUD_BASE_URL="https://provider.example/v1"
export WANGSHENG_CLOUD_MODEL="replace-with-model-name"
export WANGSHENG_CLOUD_API_KEY="replace-with-secret"
```

The runtime does not print or persist the API key.

## Real native-tool smoke test

Run one frozen scenario once:

```bash
python -m wangsheng.cli cloud-tool-smoke \
  --scenario-id normal_observe_and_report \
  --output-dir artifacts/cloud-tool-smoke
```

This command succeeds only when the model returns exactly one valid native tool call and the selected first action is inside the frozen acceptable set.

## Twenty-scenario first-action experiment

Run each scenario once to validate endpoint compatibility:

```bash
python -m wangsheng.cli run-cloud-first-actions \
  --repeat 1 \
  --output-dir artifacts/cloud-first-action-20x1
```

After reviewing the 20x1 output, run the fixed repeated experiment:

```bash
python -m wangsheng.cli run-cloud-first-actions \
  --repeat 10 \
  --output-dir artifacts/cloud-first-action-20x10
```

Outputs:

- `provider_config.json` without credentials
- `results.jsonl` with one record per model turn
- `results.csv` for analysis
- `summary.json` with protocol rate, semantic first-action rate, forbidden selections, Gateway rejections, latency and token totals

## Protocol boundary

The production path is now:

```text
native API tool_calls
→ Action
→ Tool Schema
→ Action Gateway
→ Executor / UE later
→ ActionResult
→ next model turn
```

The old strict text-JSON parser remains only for deterministic regression and malformed-output tests. It is not the formal cloud-model protocol.

## What v0.4.0 does not prove yet

This release contains the real provider and experiment harness, but the repository itself does not include a successful external-model result. A result is evidence only after the user runs a fixed named model and stores the generated experiment artifacts outside Git.

It also does not yet provide:

- complete multi-step cloud-model task evaluation
- failure-result replanning metrics
- local 9B/GGUF comparison
- production memory persistence and belief updates
- Unreal Engine integration
- voice, animation, LoRA or AIGC integration
