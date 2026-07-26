# WangSheng Agent Lab

Reliability-first framework for AI-controlled game NPCs.

Version 0.4.2 adds the formal multi-step cloud Episode Runner after the v0.4.1 DeepSeek first-action blind test reached 95% protocol validity and 85% semantic pass.

The model remains an action proposer. Authoritative world state, permission checks, hard constraints, action execution, memory access, and task completion remain deterministic.

## v0.4.2 milestone

- `run-cloud-episodes` performs complete model → Gateway → Executor → Observation loops
- exactly one native tool call is accepted per active Tick
- task calls use `tool_choice=required`
- dialogue-only calls use `tool_choice=auto` and must make no world-action call
- provider and policy protocol failures terminate the formal Episode immediately
- failed Gateway/Executor results are returned to the model on the next Tick
- frozen scenario events and max-step limits are reused unchanged
- a non-empty output directory is rejected to prevent evidence overwrite
- sanitized request messages, tool schemas, response messages, usage, latency, and hashes are recorded
- actual hard violations are computed from authoritative state changes
- hidden canonical target references are detected even when the Gateway could resolve them
- episode pass, clean pass, objective completion, groundedness, replanning, target errors, provider errors, latency, and Token metrics are emitted
- post-terminal checks do not make another model request
- all v0.4.1 first-action, deterministic scenario, Golden Trace, and native-tool tests remain covered

The eight tools remain:

`move_to`, `observe`, `listen_at`, `ask_through`, `open`, `close`, `report`, `wait`

## Install and deterministic verification

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m wangsheng.cli run-all-scripted \
  --scenario-dir scenarios \
  --output-dir artifacts/scripted
python tools/replay_trace.py \
  golden_traces/normal_observe_and_report.json
```

Expected source-package verification:

```text
94 tests passed
20/20 deterministic scripted scenarios
0 executed hard violations
0 incomplete traces
```

## Configure one cloud model

Keep credentials outside Git:

```bash
export WANGSHENG_CLOUD_BASE_URL="https://provider.example/v1"
export WANGSHENG_CLOUD_MODEL="replace-with-model-name"
read -rsp "API key: " WANGSHENG_CLOUD_API_KEY
echo
export WANGSHENG_CLOUD_API_KEY
```

The runtime does not print or persist the API key.

## First-action experiment

```bash
python -m wangsheng.cli run-cloud-first-actions \
  --repeat 1 \
  --output-dir /tmp/wangsheng-first-action-20x1
```

This command measures only the first model action. It does not execute a complete Episode.

## Multi-step Episode experiment

Use a fresh output directory:

```bash
python -m wangsheng.cli run-cloud-episodes \
  --base-url "https://api.deepseek.com" \
  --model "deepseek-v4-pro" \
  --tool-choice required \
  --temperature 0 \
  --top-p 1 \
  --max-tokens 256 \
  --timeout 120 \
  --max-retries 0 \
  --retry-backoff 0 \
  --extra-body-json '{"thinking":{"type":"disabled"}}' \
  --output-dir /tmp/wangsheng-v042-deepseek-20episodes
```

Default provider behavior sends `parallel_tool_calls=false`. Use `--no-send-parallel-tool-calls` only when a provider rejects that field and record the deviation.

Outputs:

```text
provider_config.json
experiment_manifest.json
results.jsonl
results.csv
summary.json
traces/<scenario>.jsonl
reports/<scenario>.json
```

Do not selectively rerun failures or reuse a non-empty result directory.

## Runtime boundary

```text
ModelVisibleWorld + current_affordances
→ native API tool call
→ alias resolution
→ Tool Schema and Gateway
→ Executor
→ ActionResult / Observation
→ next model Tick
→ Evaluator terminal decision
```

The model cannot directly write world state or declare task completion.

## Model-visible versus authoritative state

```text
FullWorldSnapshot
  save/debug/evaluator/trace authority
  may contain canonical IDs and simulator-only fields

ModelVisibleWorld
  actor-accessible facts, memories, objects and anonymous entities only
  excludes hidden identity and simulator control fields
```

An anonymous ID such as `visitor.front_001` means only that a visitor entity is known. It does not reveal a verified identity.

## Evidence limits

v0.4.2 makes multi-step validation possible. It does not by itself prove:

- production-ready NPC behavior
- stable repeated model quality
- local 9B/GGUF viability
- long-term relationship and memory coherence
- Unreal Engine integration
- ordinary-player hardware performance

See `docs/CLOUD_EPISODE_SPEC_V0.4.2.md` for metric definitions and formal-run rules.

## Controlled repository handoff

Hermes must apply the reviewed patch on the exact v0.4.1 base commit and run deterministic verification before any real-model Episode experiment. See `docs/HERMES_V0.4.2_APPLY_AND_VERIFY.md`.
