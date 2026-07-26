# WangSheng Agent Lab v0.5 Local Model Baseline SPEC

**Status:** Draft for freeze
**Target version:** `v0.5.0`
**Frozen parent:** `main@27ae3a9fc228f31b900872b96762cc80f24bc307` / tag `v0.4.3`
**Proposed branch:** `feat/local-model-baseline-v0.5`
**Primary hardware:** Lenovo Y7000 laptop, NVIDIA RTX 4060 Laptop GPU (8 GB VRAM class)
**Purpose:** determine whether the v0.4.3 NPC Core can run locally, privately and economically on consumer hardware without weakening its world, safety or evaluation contracts.

---

## 1. Decision summary

v0.4.3 closed the cloud architecture phase with a frozen DeepSeek result of 23/25 official passes, 100% protocol validity, 100% grounded episodes, zero hard violations, zero hallucinated targets and zero knowledge violations. v0.5 does **not** redesign the NPC architecture and does **not** optimize DeepSeek further.

v0.5 introduces a pinned `llama.cpp` OpenAI-compatible local inference backend, evaluates official GGUF models under controlled hardware profiles, and records both behavior quality and runtime cost. The existing WangSheng `OpenAICompatibleToolCallingProvider`, Episode Runner, Gateway, Executor, Evaluator, ModelVisibleWorld, Fact IDs and 25-scenario evaluation contract remain authoritative.

The phase answers two different questions:

1. **Capability ceiling:** can a locally hosted 8B-class model preserve most of the cloud-validated behavior?
2. **Shipping budget:** can a smaller model operate within a GPU-memory and latency budget that leaves room for an actual UE5 game?

A model passing only the capability profile is evidence of local feasibility, but is not sufficient for UE integration. At least one shipping-budget profile must pass the shipping gate before v0.6.

---

## 2. Scope

### 2.1 In scope

- Pin and run `llama.cpp` / `llama-server` as the local inference backend.
- Reuse the existing OpenAI-compatible native tool-call boundary.
- Add provider-neutral local runtime preflight and manifest capture.
- Add local-model behavior experiments for the frozen 20 regression and 5 holdout scenarios.
- Capture prompt-processing speed, generation speed, TTFT, request latency, episode latency, VRAM, RAM and process stability.
- Compare local results against the frozen v0.4.3 DeepSeek baseline without changing scenarios or scoring.
- Test one capability profile and one shipping-budget profile; allow one conditional quantization comparison.
- Preserve private experiment artifacts outside public Git.

### 2.2 Explicitly out of scope

- UE5 integration.
- Multi-NPC simulation.
- Long-term `留名簿` memory-version implementation.
- LoRA, QLoRA, SFT or preference training.
- Qwen-Agent as the runtime loop.
- vLLM, Ollama or LM Studio as the formal backend.
- Cloud fallback during formal local runs.
- Built-in llama.cpp filesystem, shell or MCP tools.
- Changing Prompt, Tool Schema, Gateway, Executor, Evaluator, ModelVisibleWorld, Fact IDs, completion conditions, scenario files or expected outcomes to help a local model.
- Reclassifying the two frozen Runtime Regression path cases after seeing model output.

---

## 3. Frozen baseline

The implementation and all formal experiments must begin from:

```text
repository: xieshutao/wangsheng-agent-lab
branch: main
commit: 27ae3a9fc228f31b900872b96762cc80f24bc307
tag: v0.4.3
```

Required preconditions:

- `git rev-parse HEAD` equals the frozen commit.
- `git status --short` is empty.
- All v0.4.3 tests pass.
- The original 20 deterministic scenarios pass.
- The 5 frozen holdout scenarios pass.
- Golden Trace replay passes with exact record and digest matches.
- No raw v0.4.3 experiment archive exists in Git history.

Frozen cloud comparison values:

| Metric | v0.4.3 DeepSeek |
|---|---:|
| Regression pass | 18/20 (90%) |
| Holdout pass | 5/5 (100%) |
| Overall official pass | 23/25 (92%) |
| Protocol valid | 25/25 (100%) |
| Grounded | 25/25 (100%) |
| Hard violations | 0 |
| Hallucinated targets | 0 |
| Knowledge violations | 0 |
| Provider errors | 0 |
| Repeated loops | 0 |
| Mean steps, regression set | 2.55 |
| Total tokens, regression set | 141,286 |
| Mean tokens per regression episode | 7,064 |

These values are comparison evidence, not mandatory local-model targets.

---

## 4. Architectural boundary

### 4.1 Required topology

```text
WangSheng Episode Runner
        │
        │ OpenAI-compatible /v1/chat/completions
        ▼
llama-server on 127.0.0.1
        │
        ▼
Pinned local GGUF model
```

`llama-server` is an inference service only. It must not execute WangSheng tools, mutate WorldState, access files, run shell commands or own the agent loop.

WangSheng remains responsible for:

- model-visible context;
- native tool schemas;
- alias resolution;
- Gateway validation;
- Executor state changes;
- Evaluator completion;
- traces and metrics.

### 4.2 Provider reuse

The existing `OpenAICompatibleToolCallingProvider` must remain the primary transport. The implementation may add provider-neutral metadata fields and a local CLI wrapper, but must not fork the Episode Runner or duplicate the tool parser.

Formal local requests use:

```text
base_url: http://127.0.0.1:8080/v1
api_key: absent or a non-secret dummy value
stream: false
temperature: 0
top_p: 1
max_tokens: 256
task tool_choice: required
dialogue-only tool_choice: auto
parallel_tool_calls: false
max_retries: 0
thinking: disabled
```

For Qwen3 through llama.cpp, non-thinking mode should be requested through provider-supported chat-template arguments rather than by editing the WangSheng Prompt.

### 4.3 Network and security boundary

- Bind the local server to `127.0.0.1` only.
- Do not expose port 8080 to LAN, public interfaces or tunnels.
- Do not enable llama.cpp built-in tools.
- Do not send local experiment contexts to any cloud endpoint.
- Model files, runtime binaries and artifacts must not enter Git.
- Formal manifests may contain model hashes, runtime versions and hardware facts, but not private paths containing the user name.

---

## 5. Pinned inference runtime

### 5.1 Reference runtime

Initial formal runtime:

```text
project: ggml-org/llama.cpp
release: b9637
reference commit: aedb2a5
backend: Windows x64 CUDA 12 package, or a reproducible CUDA build from the same release
```

The exact downloaded archive or locally built binaries must be hashed and recorded. Do not silently replace the pinned release with a newer build during an experiment.

A SPEC revision is required if the pinned build cannot correctly expose the selected model's tool-call template.

### 5.2 Mandatory server properties

- OpenAI-compatible `/v1/chat/completions` endpoint available.
- `/health` returns ready before testing.
- `/v1/models` returns the configured alias.
- Tool-aware Jinja template is active.
- Parallel decoding slots fixed to one for the formal baseline.
- Flash attention enabled where supported.
- Context size fixed per profile.
- GPU offload configuration recorded exactly.
- Context shifting disabled for formal episodes if the runtime supports that setting; an episode exceeding context is a failure, not a silent truncation.

### 5.3 Server launch record

Every formal run stores:

- llama.cpp release and commit;
- binary SHA-256;
- complete server arguments;
- model alias;
- model file path basename and SHA-256;
- model metadata from `/v1/models`;
- tool/chat template information from runtime properties where available;
- CUDA/runtime and NVIDIA driver versions;
- OS build;
- CPU model and logical/physical core count;
- installed RAM;
- GPU model and VRAM total.

---

## 6. Model matrix

Only official Qwen GGUF repositories are mandatory in v0.5. Community conversions and experimental licenses are excluded from formal evidence unless this SPEC is revised.

### 6.1 Profile A — local capability ceiling

```text
model repository: Qwen/Qwen3-8B-GGUF
file: Qwen3-8B-Q4_K_M.gguf
model size: approximately 5.03 GB
context: 8192
GPU offload: maximum/full if stable
purpose: determine the highest practical local behavior quality on the RTX 4060 laptop
```

This is the first formal behavior run.

### 6.2 Profile B — shipping-budget candidate

```text
model repository: Qwen/Qwen3-4B-GGUF
file: Qwen3-4B-Q5_K_M.gguf
model size: approximately 2.89 GB
context: 8192
GPU offload: full if stable
purpose: measure whether a smaller model leaves enough GPU headroom for a future UE5 graybox
```

The 4B profile must be tested under v0.4.3's structured Fact ID and progress contracts; old pre-v0.4.3 4B results are not comparable.

### 6.3 Profile C — conditional quantization sensitivity

```text
model repository: Qwen/Qwen3-8B-GGUF
file: Qwen3-8B-Q5_K_M.gguf
model size: approximately 5.85 GB
context: 8192
purpose: determine whether Q5 materially improves behavior over Q4
```

Profile C is run only if all conditions hold:

- Profile A completes without server crash or OOM;
- Profile A has zero hard violations and zero hallucinated targets;
- Profile A official pass is between 55% and 84%, or its failures plausibly indicate quantization-sensitive tool selection;
- Q5 fits without changing context size or other experiment semantics.

Do not run Profile C merely to search for a more favorable score.

### 6.4 Model exclusion rules

Do not use a candidate in formal evidence when:

- license or redistribution status is unclear;
- the GGUF source or conversion cannot be pinned and hashed;
- the runtime falls back to generic prose parsing instead of native/structured tool calls without explicit approval;
- tool calls require changing WangSheng schemas;
- model output requires a hidden repair prompt or manual editing;
- a model is vision-language and requires a projector not used by the text-only test;
- the model cannot run in non-thinking mode consistently.

---

## 7. Hardware profiles and resource budgets

### 7.1 Capability profile budget

This profile may use most of the GPU to establish a local quality ceiling.

| Resource | Limit / record |
|---|---:|
| Peak dedicated VRAM | must remain below physical capacity; target ≤ 7.5 GiB |
| Added system RAM | target ≤ 10 GiB |
| Context | 8192 |
| Concurrent inference slots | 1 |
| Server restarts during formal 25 | 0 |

Passing this profile alone does not authorize UE5 integration.

### 7.2 Shipping profile budget

This profile represents a future game-coexistence target.

| Resource | Gate |
|---|---:|
| Peak dedicated VRAM | ≤ 4.5 GiB |
| Added system RAM | ≤ 8 GiB |
| Context | 8192 |
| Concurrent inference slots | 1 |
| Mean model-call latency | ≤ 3.5 s |
| P95 model-call latency | ≤ 6.0 s |

If Profile B exceeds 4.5 GiB, it may still be reported, but it fails the shipping-memory gate. Do not lower context, reduce prompt contents or alter evaluation to make it pass. A later SPEC may define partial GPU offload as a separate profile.

---

## 8. Experiment phases

### Phase 0 — implementation without model download

Required code changes:

- provider-neutral local runtime manifest;
- local health/model/template preflight;
- optional parsing of llama.cpp `timings` metadata;
- resource telemetry collector;
- local experiment CLI or wrapper that reuses the existing Episode Runner;
- frozen output schema and tests;
- private artifact path enforcement;
- scripts for deterministic verification and formal local execution.

No model is downloaded and no local LLM is invoked during this phase.

### Phase 1 — deterministic and synthetic contract verification

Before any formal 25-scenario run:

1. Run all existing tests.
2. Run the original 20 deterministic scenarios.
3. Run the 5 holdout deterministic scenarios.
4. Replay Golden Trace exactly.
5. Launch the selected local server.
6. Verify `/health`, `/v1/models` and template/tool properties.
7. Run a synthetic tool contract that is not one of the 25 game scenarios.

Synthetic contract requirements:

- exactly 5 requests;
- one simple tool with a strict object schema;
- `tool_choice=required`;
- `parallel_tool_calls=false`;
- 5/5 responses contain exactly one parseable tool call;
- no manual retry and no provider retry;
- no game scenario command or expected action is included.

If the synthetic contract fails, stop. Do not run the formal 25 scenarios.

### Phase 2 — llama-bench performance baseline

For each formal model/profile, run `llama-bench` with JSON output and at least five repetitions for:

- prompt processing at 512 tokens;
- prompt processing at 2048 tokens;
- text generation at 128 tokens;
- prompt + generation at a representative context depth where supported.

Record prompt-processing and generation tokens per second. Note that `llama-bench` excludes some application-level overhead, so it is supplementary to end-to-end WangSheng timings.

### Phase 3 — formal behavior run

For each eligible profile:

- one Regression episode per original scenario: 20 total;
- one Holdout episode per frozen holdout scenario: 5 total;
- no repeat of a failed episode;
- no server restart during the 25 episodes;
- no modification of source, scenarios, prompts, tools, model parameters or runtime flags after the first episode;
- formal output directory must not already exist;
- each profile uses a distinct output directory and manifest;
- run order is frozen and recorded.

A profile may be rerun only when the first run is invalidated by an objectively external infrastructure failure before a model response was obtained, and only after a written invalidation record. Model errors, malformed tool arguments, OOM during inference, timeouts and server crashes are formal failures and are not selectively rerun.

### Phase 4 — stability and drift check

After the 25th episode, without restarting the server:

- run the same synthetic contract once;
- record process RSS and GPU VRAM;
- compare against post-warmup values;
- record whether latency or memory drifted.

Target drift after warm-up:

```text
process RSS growth ≤ 15%
VRAM growth ≤ 10%
no unreleased context/session accumulation
```

---

## 9. Metrics and output schema

### 9.1 Behavior metrics

Retain all v0.4.3 metrics and split them by Regression, Holdout and Overall:

- official pass and rate;
- clean pass;
- scenario outcome met;
- objective completed;
- protocol valid;
- grounded;
- unexpected no-tool calls;
- dialogue no-tool calls;
- multiple tool calls;
- selected forbidden tools;
- Gateway rejections and reasons;
- execution failures;
- target errors;
- hallucinated targets;
- knowledge violations;
- actual hard violations;
- repeated loops;
- provider and policy errors;
- incomplete traces;
- recovered-after-failure;
- steps and model-call counts;
- complete per-episode action sequence.

### 9.2 End-to-end performance metrics

Per request:

- request start/end monotonic timestamps;
- total latency;
- TTFT when available;
- prompt tokens;
- cached prompt tokens when available;
- completion tokens;
- prompt processing milliseconds and tokens/second;
- generation milliseconds and tokens/second;
- finish reason;
- context tokens used.

Per episode:

- total latency;
- mean/P95 request latency;
- total prompt/completion tokens;
- maximum context use;
- steps;
- server errors.

Per profile:

- model load time;
- `llama-bench` results;
- mean/P50/P95/max model-call latency;
- mean/P95 episode latency;
- prompt and generation throughput;
- peak VRAM;
- peak system RAM and process RSS;
- CPU/GPU utilization samples;
- thermal or power throttling indicators where available;
- server crash/OOM count;
- memory drift.

### 9.3 Artifact structure

```text
<private-root>/v050-local/<profile-id>/
  runtime_manifest.json
  hardware_manifest.json
  model_manifest.json
  server_args.txt
  server_stdout.log
  server_stderr.log
  health_preflight.json
  synthetic_contract.jsonl
  llama_bench.json
  telemetry.csv
  results.jsonl
  results.csv
  summary.json
  reports/
  traces/
  sanitized_report.json
  checksums.sha256
```

Raw local traces remain private by default. Public Git stores only a sanitized report, aggregate metrics, exact hashes and reproduction instructions.

---

## 10. Acceptance gates

### 10.1 Non-negotiable safety and integrity gate

Every profile intended for further use must satisfy:

```text
actual_hard_violation_count = 0
hallucinated_target_count = 0
trace_incomplete_count = 0
selected_forbidden_tool_count = 0
source_modified_during_run = false
selective_rerun = false
```

A profile violating any item is not eligible regardless of pass rate.

### 10.2 Capability profile classification

| Result | Classification |
|---|---|
| Pass ≥ 70%, protocol ≥ 95%, grounded ≥ 90%, safety gate passes | Local capability validated |
| Pass 55–69%, protocol ≥ 95%, safety gate passes | Promising; analyze common failures |
| Pass 35–54%, protocol ≥ 90%, safety gate passes | Limited router only; deterministic decomposition required |
| Pass < 35% or protocol < 90% | Candidate unsuitable for current contract |

Performance target for a positive capability result:

```text
mean model-call latency ≤ 2.5 s
P95 model-call latency ≤ 5.0 s
generation throughput ≥ 20 tokens/s
```

Failure to meet performance targets does not erase behavior evidence, but blocks an interactive-runtime classification.

### 10.3 Shipping profile gate for v0.6

v0.6 UE5 graybox may begin only if at least one profile satisfies all of:

```text
overall official pass ≥ 60%
Regression pass ≥ 60%
Holdout pass ≥ 60%
protocol valid ≥ 95%
grounded ≥ 90%
knowledge violation episodes ≤ 1
actual hard violations = 0
hallucinated targets = 0
trace incomplete = 0
provider errors = 0
P95 model-call latency ≤ 6.0 s
peak dedicated VRAM ≤ 4.5 GiB
server completes 25 episodes without restart or OOM
```

If only Profile A passes behavior but no profile passes shipping memory/latency, the next task is a separate local-runtime optimization or smaller-model study, not UE5 integration.

### 10.4 No production claim

Passing v0.5 permits only:

```text
Eligible for UE5 single-room local-inference integration spike
```

It does not prove production readiness, long-session stability, multi-NPC operation or broad consumer hardware support.

---

## 11. Stop conditions

Stop the phase and report without improvising when:

- frozen commit or tag mismatch;
- dirty worktree before a formal run;
- model or runtime checksum mismatch;
- tool-aware template cannot be verified;
- synthetic tool contract is below 5/5;
- server binds beyond loopback;
- formal output directory already exists;
- any source/scenario/prompt/evaluator file changes during a run;
- provider retries are nonzero;
- a model requires manual response repair;
- server OOMs or crashes;
- trace count differs from episode count;
- private artifacts are staged in Git;
- hardware telemetry cannot be collected sufficiently to evaluate the selected profile.

Do not lower gates or change the test set during the same formal run.

---

## 12. Required implementation deliverables

The implementation phase must produce, at minimum:

1. `docs/LOCAL_MODEL_BASELINE_SPEC_V0.5.md` — this frozen SPEC.
2. `docs/LOCAL_MODEL_RUNTIME_GUIDE_V0.5.md` — installation and local execution guide.
3. `src/wangsheng/local_runtime.py` or equivalent provider-neutral preflight/manifest module.
4. Optional provider metadata extension for llama.cpp `timings`, without breaking cloud traces.
5. `run-local-episodes` CLI or a strictly local wrapper reusing the same experiment engine.
6. Hardware/resource telemetry collector with testable parsers.
7. Synthetic tool-contract fixture unrelated to the 25 game scenarios.
8. Windows PowerShell launch scripts for the pinned llama.cpp runtime and each required profile.
9. Deterministic verification script for v0.5.
10. Unit/integration tests using a fake local HTTP server; tests must not require a GPU or model.
11. Private artifact safeguards and `.gitignore` coverage.
12. Model/runtime license and provenance entries in the reuse matrix or third-party notice documentation.

Implementation must not download multi-gigabyte models in automated tests.

---

## 13. Roles and execution boundaries

### Technical lead / this conversation

- freezes architecture and metrics;
- writes implementation and tests when code work begins;
- audits diffs and experiment traces;
- selects the next gate.

### Hermes

- applies reviewed patches;
- verifies exact commit and checksums;
- runs deterministic checks;
- starts/stops the pinned local runtime when it has access to the target PC;
- collects and preserves artifacts;
- commits only approved source/document changes.

Hermes must not redesign the runtime, change model selection, repair outputs or tune parameters after seeing formal results.

### User / Creative Director

- approves disk downloads and local-machine use;
- confirms which machine is the target shipping baseline;
- decides whether the achieved quality/latency tradeoff is acceptable for the game.

---

## 14. Planned sequence after SPEC freeze

```text
Freeze this SPEC on main
        ↓
Implement v0.5 local runtime/preflight/telemetry without a model
        ↓
Deterministic tests and fake-server integration tests
        ↓
Pin implementation commit
        ↓
Download and hash Profile A model locally
        ↓
Synthetic contract → llama-bench → formal 25
        ↓
Audit Profile A
        ↓
Run Profile B under the same frozen code
        ↓
Run Profile C only if its conditional gate is met
        ↓
Classify local capability and shipping feasibility
        ↓
Either v0.6 UE5 single-room spike or a separate local optimization/model study
```

---

## 15. Freeze checklist

- [ ] Parent commit equals `27ae3a9fc228f31b900872b96762cc80f24bc307`.
- [ ] This SPEC is committed before implementation begins.
- [ ] Runtime version and model repositories are pinned.
- [ ] No gameplay contract changes are permitted in v0.5.
- [ ] Regression and Holdout are reported separately.
- [ ] Capability and shipping profiles are not conflated.
- [ ] Synthetic smoke is not one of the 25 formal scenarios.
- [ ] No cloud fallback is permitted.
- [ ] Local server is loopback-only and built-in tools are disabled.
- [ ] Formal runs have zero retries and zero selective reruns.
- [ ] Raw traces and model files remain outside public Git.
- [ ] UE5 begins only after the shipping profile gate.

---

## 16. Primary upstream references

The implementation must consult and pin the following primary sources rather than third-party tutorials:

- `ggml-org/llama.cpp` server documentation and function-calling documentation.
- `ggml-org/llama.cpp` release `b9637` and its published binary checksums.
- `ggml-org/llama.cpp` `llama-bench` documentation.
- `Qwen/Qwen3-8B-GGUF` official model repository.
- `Qwen/Qwen3-4B-GGUF` official model repository.
- Qwen3 official model cards for non-thinking mode and agent/tool use.

No source code from these projects is copied into WangSheng merely by following this SPEC. `llama.cpp` is a separately pinned inference runtime; Qwen GGUF files are separately licensed model artifacts.

---

**Freeze decision:** once committed, implementation may begin. Model download and formal local inference remain blocked until the v0.5 implementation patch passes deterministic review.
