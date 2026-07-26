# WangSheng Agent Lab v0.6 Headless Game Bridge SPEC

**Status:** Draft for freeze  
**Target version:** `v0.6.0`  
**Frozen parent:** `main@987e9c0` / tag `v0.5.1` (Hermes must record the full commit hash before applying this SPEC)  
**Proposed SPEC branch:** `docs/headless-game-bridge-spec-v0.6`  
**Proposed implementation branch:** `feat/headless-game-bridge-v0.6`  
**Purpose:** convert the validated NPC Core from a synchronous text micro-world into a transport-neutral, asynchronous, continuously advancing game-world integration boundary that can later be implemented by UE5 without changing model, Gateway, Executor, task, knowledge, or safety contracts.

---

## 1. Decision summary

v0.5.1 closed the local-model reliability phase with a frozen Qwen3-4B Q5 result of `27/30 (90%)`, `100%` protocol validity, `100%` structured grounding, zero hard violations, zero hallucinated targets, zero knowledge violations, zero provider errors, deterministic report rendering, and dialogue/world-action isolation.

v0.6 does **not** attempt to improve that score. It does **not** add more door benchmark cases, modify the existing model prompt, widen the model tool surface, or begin the `留名簿` memory system.

v0.6 introduces a Headless Game Bridge with four responsibilities:

1. maintain a continuously advancing authoritative game world;
2. execute NPC actions asynchronously through an explicit lifecycle;
3. prevent duplicate, stale, cancelled, or late actions from mutating the world;
4. expose a transport-neutral message protocol that a future UE5 adapter can implement.

The reference implementation must be deterministic and runnable on the existing cloud/VPS environment without UE5 and without a GPU. Real-model integration is a later v0.6 validation step, not a prerequisite for the deterministic bridge core.

---

## 2. Frozen baseline

The SPEC freeze and implementation must begin from the public repository state where:

```text
repository: https://github.com/xieshutao/wangsheng-agent-lab
branch: main
tag: v0.5.1
expected short commit prefix: 987e9c0
```

Hermes must record and return:

```text
git rev-parse main
git rev-list -n 1 v0.5.1
```

The two full hashes must match before any v0.6 branch is created.

Required baseline evidence:

- `pytest` passes all 125 frozen tests;
- Regression `20/20` deterministic scenarios pass;
- v0.4.3 Holdout `5/5` passes;
- v0.5.1 Holdout `5/5` passes;
- Golden Trace passes with exact records and digest;
- Golden digest remains:

```text
f405bb9e5d3953abeeda32a547eea5c20dce69e2ce575879c504dd203d4cb88c
```

Frozen v0.5.1 behavior files must not be changed merely to make the bridge easier to implement.

---

## 3. Scope

### 3.1 In scope

- a transport-neutral bridge protocol and canonical message envelope;
- a deterministic headless game world with a virtual clock;
- asynchronous action lifecycle and one active world action per NPC;
- world snapshots and ordered world deltas;
- optimistic concurrency using world epoch and world version;
- idempotent message and action handling;
- stale decision rejection;
- player/task cancellation;
- pause and resume semantics;
- action timeout and external interruption;
- save/load with canonical gameplay-state digest;
- deterministic event scheduling;
- in-memory reference transport;
- JSONL trace/replay transport for debugging and reproducibility;
- bridge-to-existing-NPC-Core adapter;
- deterministic integration tests and accelerated soak tests;
- optional later Qwen3-4B real-model bridge smoke after deterministic acceptance.

### 3.2 Explicitly out of scope

- UE5 code, Blueprints, C++ modules, animation, NavMesh, physics, Control Rig, Behavior Trees, Mass AI, or Gameplay Ability System integration;
- network exposure, authentication, multiplayer, remote public APIs, or cloud orchestration;
- more than one controlled NPC;
- combat, inventory, trading, crafting, ownership, economy, or procedural navigation;
- long-term memory, reflection, relationship simulation, or `留名簿` memory versions;
- model training, LoRA, QLoRA, SFT, preference optimization, or model replacement;
- changing the frozen 30-Episode benchmark, Prompt, existing tool definitions, Gateway semantics, deterministic fact renderer, or model evaluation scores;
- using wall-clock time as the source of truth in deterministic tests;
- allowing the language model to mutate game state directly.

---

## 4. Architectural boundary

### 4.1 Required topology

```text
Player / scripted events
        │
        ▼
Headless Game World  ───── authoritative physical state and virtual time
        │
        │ snapshots, deltas, action outcomes
        ▼
Headless Game Bridge ───── protocol, ordering, idempotency, cancellation
        │
        ▼
WangSheng NPC Core   ───── task, ModelVisibleWorld, Gateway, knowledge, traces
        │
        ▼
Model Provider        ───── optional in deterministic phase
```

The world and the NPC Core must not share mutable Python objects. All integration must cross a defined message or adapter boundary.

### 4.2 Authority ownership

| Concern | Authoritative owner |
|---|---|
| Physical position | Headless Game World |
| Door/path state | Headless Game World |
| Virtual time | Headless Game World |
| Active action progress | Headless Game World |
| Player pause/cancel input | Headless Game World |
| Task intent and completion contract | WangSheng NPC Core |
| Model-visible projection | WangSheng NPC Core |
| Knowledge and Fact IDs | WangSheng NPC Core |
| Tool legality | Gateway |
| Game mutation | Headless Game Executor only |
| Natural-language factual rendering | Existing deterministic renderer |
| Trace and evaluation | WangSheng trace/evaluation layer |

No bridge message from the model or provider may directly assign a position, door state, world version, task status, or fact.

### 4.3 Existing model contract

v0.6 must preserve the existing model-facing action contract. The bridge may adapt an accepted action into a headless game command, but it must not create a second model-specific tool schema.

The model continues to propose one immediate action. Gateway continues to validate model-visible identity, parameters, permissions, task constraints, and knowledge boundaries before the bridge receives an action request.

---

## 5. Canonical protocol envelope

Every bridge message must serialize to canonical JSON and contain:

```json
{
  "protocol_version": "0.6",
  "message_id": "msg_...",
  "message_kind": "ACTION_REQUESTED",
  "session_id": "session_...",
  "world_id": "world_...",
  "world_epoch": "epoch_...",
  "world_version": 42,
  "sequence": 108,
  "tick_id": "tick_...",
  "task_id": "task_...",
  "action_id": "action_...",
  "correlation_id": "msg_...",
  "causation_id": "msg_...",
  "virtual_time_ms": 12500,
  "payload": {}
}
```

### 5.1 Field rules

- `protocol_version` is fixed to `0.6` for this phase.
- `message_id` is globally unique within an experiment archive.
- `session_id` identifies one running bridge process/session.
- `world_id` identifies the save/world lineage.
- `world_epoch` changes after reset or load and invalidates all earlier pending replies.
- `world_version` is monotonic within an epoch and increments on every authoritative state mutation.
- `sequence` is monotonic for every emitted bridge message and detects missing or reordered messages.
- `tick_id` associates bridge activity with an NPC Core decision tick where applicable.
- `task_id` and `action_id` may be absent only for message kinds where they are not meaningful.
- `correlation_id` links replies to requests.
- `causation_id` identifies the message that directly caused the current message.
- `virtual_time_ms` comes from the deterministic game clock, not the system wall clock.
- `payload` must validate against the schema for `message_kind`.

Unknown fields are rejected in formal deterministic tests. Unknown `message_kind` values are rejected with a structured protocol error and must not mutate state.

---

## 6. Required message kinds

### 6.1 Session and state

```text
HELLO
HELLO_ACK
WORLD_SNAPSHOT
WORLD_DELTA
WORLD_EVENT
HEARTBEAT
PROTOCOL_ERROR
```

### 6.2 Task lifecycle

```text
TASK_ASSIGNED
TASK_CANCELLED
TASK_TERMINATED
```

### 6.3 Action lifecycle

```text
ACTION_REQUESTED
ACTION_ACCEPTED
ACTION_REJECTED
ACTION_STARTED
ACTION_COMPLETED
ACTION_FAILED
ACTION_CANCEL_REQUESTED
ACTION_CANCELLED
ACTION_EXPIRED
```

### 6.4 Game lifecycle

```text
GAME_PAUSED
GAME_RESUMED
SAVE_REQUESTED
SAVE_COMPLETED
LOAD_REQUESTED
LOAD_COMPLETED
WORLD_RESET
```

The implementation may use internal Python event types, but the externally logged canonical record must map to one of these kinds.

---

## 7. Action lifecycle

### 7.1 State machine

```text
REQUESTED
   ├─> REJECTED
   └─> ACCEPTED
          └─> STARTED
                 ├─> COMPLETED
                 ├─> FAILED
                 ├─> CANCELLED
                 └─> EXPIRED
```

A terminal action state is immutable. An action can reach exactly one terminal state.

### 7.2 Required request fields

An `ACTION_REQUESTED` payload must include:

```json
{
  "actor_id": "npc.core",
  "action_name": "move_to",
  "arguments": {"target_id": "door.front"},
  "based_on_world_epoch": "epoch_...",
  "based_on_world_version": 41,
  "deadline_virtual_time_ms": 18000,
  "task_generation": 3
}
```

### 7.3 Validation order

Before accepting an action, the bridge must validate in this order:

1. schema and protocol version;
2. duplicate `message_id` handling;
3. duplicate `action_id` handling;
4. current `world_epoch`;
5. current or permitted `world_version`;
6. current task generation and cancellation state;
7. game pause state;
8. actor existence and availability;
9. one-active-action constraint;
10. action-specific world preconditions.

A rejection must be structured and must not partially mutate state.

### 7.4 Idempotency

- Reprocessing the same `message_id` returns the previously recorded response without new mutation.
- Reprocessing the same `action_id` with byte-identical content returns the current known action state.
- Reusing the same `action_id` with different content is a protocol violation.
- Duplicate completion callbacks must not apply effects twice.
- Every mutation record must identify the responsible `action_id` or world event.

### 7.5 Stale decisions

An action based on an old epoch is always rejected as `STALE_WORLD_EPOCH`.

An action based on an old version is rejected as `STALE_WORLD_VERSION` unless the action is explicitly declared version-insensitive. v0.6 formal actions are version-sensitive by default.

A rejected stale action is returned to the NPC Core as an observation requiring a fresh world projection and replan. It must never be silently executed.

---

## 8. Minimal headless world

### 8.1 Entities

The reference world contains:

- one player;
- one controlled NPC;
- one visitor;
- one front door;
- one counter or paper-crane observation object;
- three navigation anchors: player position, counter position, door position.

Internal entity IDs remain authoritative and may differ from model-visible aliases.

### 8.2 World state

Minimum canonical gameplay state:

```json
{
  "virtual_time_ms": 0,
  "paused": false,
  "entities": {},
  "door": {
    "open": false,
    "locked": false,
    "reachable": true
  },
  "visitor": {
    "present": true,
    "claimed_name": "Xiaoman",
    "purpose": "request_medicine",
    "request": "speak_to_player"
  },
  "active_actions": {},
  "scheduled_events": [],
  "task_generation": 1
}
```

The saved gameplay state must not contain Python object identities, open file handles, provider clients, thread objects, or non-deterministic timestamps.

### 8.3 Virtual clock

The reference world uses a single deterministic virtual clock:

```text
advance(delta_ms)
```

Advancing time processes scheduled events in stable order using:

1. scheduled virtual time;
2. event priority;
3. insertion sequence.

Formal deterministic tests must not use `sleep()` to determine correctness.

### 8.4 Reference action durations

Exact durations are configuration data, not model-visible truth. Initial reference values:

| Action | Duration |
|---|---:|
| `move_to` adjacent anchor | 1,000 ms |
| `observe` | 500 ms |
| `listen_at` | 800 ms |
| `ask_through` | 1,200 ms |
| `report` | 600 ms |
| `wait` | requested bounded duration |

The world may fail or interrupt an action while it is in progress.

---

## 9. External events and interruption

v0.6 must support world events occurring while an NPC action or model decision is pending.

Required reference events:

- path becomes blocked or reachable;
- door becomes locked or unlocked;
- visitor leaves;
- player moves;
- player cancels the task;
- game pauses or resumes;
- save/load boundary;
- model/provider timeout notification.

Examples:

- If the path becomes blocked before `move_to` completes, the action fails once with `NO_PATH`.
- If the visitor leaves before `ask_through` completes, the action fails once with `TARGET_GONE`.
- If the player cancels the task, the active task-owned action is cancelled and late completion is ignored.
- If the game pauses, virtual time and action progress stop.
- A model reply generated before load is rejected after load because `world_epoch` changed.

---

## 10. Pause, cancellation, timeout, and provider outage

### 10.1 Pause

- `GAME_PAUSED` is an authoritative state mutation.
- Virtual time does not advance while paused.
- Active actions retain remaining duration.
- New action requests are rejected with `GAME_PAUSED` in v0.6.
- Resume does not automatically execute previously rejected actions; the NPC Core must re-evaluate.

### 10.2 Task cancellation

- Every task has a monotonic `task_generation`.
- Cancellation increments or invalidates the generation.
- Active actions owned by the cancelled task enter `CANCELLED` exactly once.
- Late provider replies or late game callbacks from an older generation cannot mutate the world.

### 10.3 Action timeout

- A deadline uses virtual time.
- An action reaching its deadline before completion enters `EXPIRED` once.
- Expiry does not apply the normal completion effect.

### 10.4 Provider outage

The headless game world must remain valid if no model response arrives.

- The world may continue to advance.
- The NPC remains idle or continues an already accepted action.
- A provider error is recorded outside the authoritative world state.
- Restarting the provider cannot replay or duplicate an already terminal action.

---

## 11. Save and load

### 11.1 Save contents

A save must include:

- schema version;
- world lineage identifier;
- gameplay-state digest;
- virtual time;
- entities and components;
- door/path/visitor state;
- active actions and remaining duration;
- scheduled world events;
- task generation and cancellation state;
- next deterministic sequence counters required to resume gameplay.

Provider clients, pending HTTP requests, wall-clock timestamps, and process IDs are excluded.

### 11.2 Load semantics

- Loading creates a new `world_epoch`.
- Gameplay state is restored from canonical JSON.
- Pending model decisions from the old epoch become stale.
- Active world actions may resume from saved remaining duration.
- Stream `sequence` restarts only if accompanied by the new epoch; message IDs remain unique.
- A `LOAD_COMPLETED` message includes the restored gameplay digest.

### 11.3 Digest rule

A canonical SHA-256 gameplay digest must be computed over stable, sorted JSON excluding transport/session metadata.

Required tests:

- save then immediate load preserves the gameplay digest;
- save during an active action preserves remaining duration and final outcome;
- load invalidates pre-load model/action replies;
- repeated load of the same save produces the same gameplay digest;
- corrupted or incompatible saves fail without changing the active world.

---

## 12. World snapshots and deltas

### 12.1 Snapshot

`WORLD_SNAPSHOT` contains the full bridge-visible authoritative world state and its digest.

### 12.2 Delta

`WORLD_DELTA` contains:

```json
{
  "from_world_version": 41,
  "to_world_version": 42,
  "operations": [],
  "state_digest_after": "sha256:..."
}
```

A consumer applying all ordered deltas after a snapshot must reconstruct the same canonical state and digest as the authoritative world.

A missing sequence, wrong `from_world_version`, or digest mismatch is a hard bridge-integrity failure.

### 12.3 Model visibility

The bridge snapshot is not automatically the model prompt. Existing `ModelVisibleWorld` logic must project only permitted information and anonymous/model-visible IDs.

---

## 13. Reference transports

### 13.1 In-memory transport

Mandatory for deterministic tests. It must preserve message order and support explicit duplicate, delay, reordering, and loss injection for fault tests.

### 13.2 JSONL trace/replay transport

Mandatory for reproducibility. Each line contains one canonical message envelope.

Required capabilities:

- append-only recording;
- replay into an empty deterministic bridge;
- verify sequence, world versions, and digests;
- redact private natural-language content when producing public evidence;
- reject malformed lines without mutating world state.

### 13.3 Future transports

HTTP, WebSocket, named pipes, sockets, or UE-specific transports are deferred. They must later implement the same canonical message and lifecycle contracts.

---

## 14. Bridge adapter to WangSheng NPC Core

The adapter must:

1. convert authoritative bridge world state into the existing internal world representation;
2. invoke existing ModelVisibleWorld projection;
3. pass accepted model actions through existing Gateway checks;
4. convert a validated action to `ACTION_REQUESTED`;
5. convert bridge terminal outcomes into existing structured observations;
6. request a new NPC tick only on defined triggers;
7. preserve existing task, fact, renderer, and knowledge contracts.

Defined decision triggers for v0.6:

- task assigned;
- action completed;
- action failed;
- action cancelled or expired;
- relevant world event;
- player dialogue/command;
- load completed;
- provider retry/recovery policy requests a new decision.

There is no per-frame model call.

---

## 15. Deterministic scenario matrix

The implementation must include at least the following bridge scenarios, separate from the frozen v0.5.1 model benchmark:

1. normal move → ask → return → report lifecycle;
2. duplicate `ACTION_REQUESTED` is idempotent;
3. duplicate completion callback does not double-mutate;
4. stale world version rejects action;
5. stale epoch after load rejects late action;
6. player cancels during movement;
7. pause freezes active action progress;
8. resume requires fresh decision after paused rejection;
9. path becomes blocked mid-move;
10. visitor leaves mid-question;
11. action expires before completion;
12. save/load while idle preserves digest;
13. save/load during active action resumes correctly;
14. corrupted save leaves current world untouched;
15. snapshot plus deltas reconstruct exact digest;
16. missing or reordered delta is detected;
17. provider timeout leaves world valid;
18. provider recovery does not duplicate an action;
19. dialogue-only turn causes no world action;
20. 10,000 accelerated scheduler events produce no state drift.

All scenario results must be machine-readable and include a trace.

---

## 16. Testing strategy

### 16.1 Phase A — protocol and state unit tests

No model, network, GPU, or wall-clock sleep.

Test:

- schemas;
- envelope validation;
- ordering;
- idempotency;
- version/epoch checks;
- action state machine;
- canonical serialization and digest;
- save/load;
- deterministic scheduler.

### 16.2 Phase B — deterministic integration tests

Use scripted policies and the real Gateway/Executor/adapter boundary.

All frozen v0.5.1 tests and Golden Trace must remain unchanged and pass.

### 16.3 Phase C — accelerated soak

Run at least:

```text
10,000 virtual scheduler events
1,000 action lifecycles
100 save/load cycles
```

Required outcomes:

- zero duplicate mutation;
- zero invalid action-state transition;
- zero sequence gap in the authoritative trace;
- zero gameplay digest mismatch;
- bounded memory growth with no unbounded retained event history in the live world object.

### 16.4 Phase D — optional real-model bridge smoke

Only after Phases A–C pass and implementation is frozen.

Use the already validated Qwen3-4B Q5 model and existing provider. This is an integration smoke, not a replacement benchmark.

The smoke must include stale reply, cancellation, timeout, and load-boundary cases. Model scores from v0.5.1 remain immutable.

---

## 17. Observability and artifacts

Every run stores:

- bridge protocol version;
- full Git commit;
- scenario manifest and SHA-256;
- canonical JSONL message trace;
- initial and final gameplay digests;
- all action lifecycle transitions;
- world-version increments and mutation cause;
- save hashes;
- provider/model metadata when a model is used;
- resource and timing metrics for soak tests;
- final machine-readable acceptance report.

Private traces and save files remain outside public Git. Public Git may include sanitized summaries, schemas, deterministic fixtures, and hashes.

Logs must never include API keys, SSH passwords, private filesystem credentials, or full private model responses unless the user explicitly stores them in private artifacts.

---

## 18. Error taxonomy

Required structured bridge errors:

```text
PROTOCOL_VERSION_UNSUPPORTED
SCHEMA_INVALID
UNKNOWN_MESSAGE_KIND
DUPLICATE_MESSAGE_CONFLICT
DUPLICATE_ACTION_CONFLICT
STALE_WORLD_EPOCH
STALE_WORLD_VERSION
STALE_TASK_GENERATION
GAME_PAUSED
ACTOR_NOT_FOUND
ACTOR_BUSY
ACTION_NOT_SUPPORTED
ACTION_PRECONDITION_FAILED
TARGET_GONE
NO_PATH
LOCKED
CANCELLED_BY_PLAYER
ACTION_TIMEOUT
SAVE_CORRUPTED
SAVE_VERSION_UNSUPPORTED
DELTA_SEQUENCE_GAP
STATE_DIGEST_MISMATCH
PROVIDER_UNAVAILABLE
INTERNAL_BRIDGE_ERROR
```

Errors are data. They must not be represented only as free-form exception text.

---

## 19. Acceptance gates

v0.6 may be tagged only if all gates pass.

### 19.1 Backward compatibility

- all frozen v0.5.1 tests pass;
- Regression 20/20 passes;
- v0.4.3 Holdout 5/5 passes;
- v0.5.1 Holdout 5/5 passes;
- Golden Trace records and digest remain exact;
- model-facing Prompt, tool schemas, Gateway behavior, deterministic renderer, and frozen scenario expectations are unchanged unless a separately approved compatibility amendment is written before implementation.

### 19.2 Protocol correctness

- 100% canonical message-schema validation;
- duplicate messages/actions cause zero duplicate mutation;
- every action reaches exactly one terminal state;
- stale epoch and stale version requests cause zero mutation;
- all authoritative messages have continuous sequence numbers;
- snapshot + delta replay produces exact final digest.

### 19.3 Cancellation and lifecycle

- player cancellation prevents later action completion effects;
- pause stops virtual action progress;
- action timeout applies no completion effect;
- provider outage and recovery cause no duplicate action;
- load invalidates all pre-load pending decisions.

### 19.4 Save/load

- idle save/load digest match: 100%;
- active-action save/load final-state match: 100%;
- repeated load determinism: 100%;
- corrupted save causes zero active-world mutation.

### 19.5 Soak

- 10,000 scheduler events complete;
- 1,000 action lifecycles complete;
- 100 save/load cycles complete;
- hard bridge-integrity violations: 0;
- state digest mismatches: 0;
- duplicate world mutations: 0;
- invalid lifecycle transitions: 0;
- incomplete traces: 0.

### 19.6 Security and authority

- model/provider cannot mutate world state directly;
- bridge binds no public network endpoint in the reference implementation;
- no credentials in traces or public fixtures;
- private runtime artifacts remain outside Git.

---

## 20. Required deliverables

The implementation phase must produce:

```text
src/wangsheng/bridge/
  protocol.py
  messages.py
  errors.py
  action_lifecycle.py
  scheduler.py
  headless_world.py
  savegame.py
  transport.py
  adapter.py

scenarios_bridge_v060/

tools/
  run_bridge_scenarios.py
  replay_bridge_trace.py
  run_bridge_soak.py

scripts/
  verify_v060.sh

tests/
  test_bridge_protocol.py
  test_bridge_action_lifecycle.py
  test_bridge_scheduler.py
  test_bridge_save_load.py
  test_bridge_transport.py
  test_bridge_adapter.py
  test_bridge_scenarios.py
  test_bridge_soak.py

docs/
  HEADLESS_GAME_BRIDGE_SPEC_V0.6.md
  HEADLESS_GAME_BRIDGE_PROTOCOL_V0.6.md
  HEADLESS_GAME_BRIDGE_STATUS_V0.6.md
```

Exact file factoring may change during implementation, but responsibilities and acceptance gates may not be weakened without a SPEC revision.

---

## 21. Implementation order

1. canonical protocol types and validation;
2. deterministic virtual clock and scheduler;
3. action lifecycle and idempotency ledger;
4. minimal authoritative headless world;
5. snapshots, deltas, and digest reconstruction;
6. pause, cancel, timeout, and interruption;
7. save/load and epoch invalidation;
8. in-memory and JSONL transports;
9. WangSheng adapter;
10. deterministic scenario suite;
11. accelerated soak tests;
12. optional real-model bridge smoke.

Do not begin with model integration. The bridge must first prove correctness under scripted deterministic control.

---

## 22. Stop conditions

Implementation must stop for review if any of the following occurs:

- existing v0.5.1 Golden Trace changes;
- implementation requires changing the model-facing tool schema;
- world and NPC Core require shared mutable objects;
- duplicate or stale events cannot be made idempotent;
- save/load requires serializing provider/network/process objects;
- deterministic tests require wall-clock sleeps;
- bridge correctness depends on Qwen-specific behavior;
- the implementation starts adding UE5, multi-NPC, combat, inventory, or long-term memory features.

These indicate a boundary error or a required SPEC revision, not permission to expand scope informally.

---

## 23. Phase completion decision

Passing v0.6 means:

> WangSheng NPC Core can control one NPC in a continuously advancing authoritative game-world simulation through an asynchronous, idempotent, saveable, replayable, transport-neutral bridge, while late model replies, cancellation, duplicate messages, pauses, timeouts, and load boundaries cannot corrupt world state.

Passing v0.6 does **not** mean:

- UE5 integration is complete;
- RTX 4060 + UE5 coexistence is validated;
- multi-NPC social simulation works;
- `留名簿` memory mechanics are implemented;
- the full game is playable.

After v0.6, the next milestone is a thin UE5 adapter implementing the same protocol, followed by the `留名簿` memory-version system.
