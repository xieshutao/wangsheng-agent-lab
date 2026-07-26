# WangSheng Headless Game Bridge Protocol v0.6

**Protocol version:** `0.6`
**Reference implementation:** `src/wangsheng/bridge/`
**Scope:** one authoritative headless world, one controlled NPC, transport-neutral asynchronous actions.

## 1. Authority model

The headless world owns physical state, virtual time, active action progress and save/load state. WangSheng NPC Core owns task intent, model-visible projection, knowledge, Fact IDs and tool legality. The model may request one immediate action but never writes world state directly.

The bridge boundary passes canonical message values. The world and NPC Core do not share mutable state objects.

## 2. Canonical envelope

Every message contains:

```json
{
  "protocol_version": "0.6",
  "message_id": "msg.00000001",
  "message_kind": "ACTION_REQUESTED",
  "session_id": "session.headless.v060",
  "world_id": "world.front_hall.v060",
  "world_epoch": "epoch.0001",
  "world_version": 0,
  "sequence": 1,
  "virtual_time_ms": 0,
  "payload": {}
}
```

Optional correlation fields are `tick_id`, `task_id`, `action_id`, `correlation_id` and `causation_id`. Unknown envelope fields are rejected. Canonical serialization is UTF-8 JSON with sorted keys and compact separators.

## 3. Ordering and concurrency

- `world_epoch` changes on load/reset and invalidates earlier pending decisions.
- `world_version` increments on each authoritative gameplay mutation.
- `sequence` increments on each emitted message within the active session stream.
- action requests are version-sensitive by default;
- stale epoch/version/task-generation requests are rejected without mutation.

## 4. Action lifecycle

```text
REQUESTED -> REJECTED
REQUESTED -> ACCEPTED -> STARTED -> COMPLETED
                                  -> FAILED
                                  -> CANCELLED
                                  -> EXPIRED
```

A terminal state is immutable. An actor may have at most one active world action. Repeated identical message/action IDs are idempotent; conflicting reuse is a structured protocol error.

Reference durations:

| Action | Duration |
|---|---:|
| `move_to` | 1000 ms |
| `observe` | 500 ms |
| `listen_at` | 800 ms |
| `ask_through` | 1200 ms |
| `report` | 600 ms |
| `wait` | bounded request duration |

## 5. Required message kinds

Session/state:

```text
HELLO HELLO_ACK WORLD_SNAPSHOT WORLD_DELTA WORLD_EVENT HEARTBEAT PROTOCOL_ERROR
```

Task lifecycle:

```text
TASK_ASSIGNED TASK_CANCELLED TASK_TERMINATED
```

Action lifecycle:

```text
ACTION_REQUESTED ACTION_ACCEPTED ACTION_REJECTED ACTION_STARTED
ACTION_COMPLETED ACTION_FAILED ACTION_CANCEL_REQUESTED ACTION_CANCELLED ACTION_EXPIRED
```

Game lifecycle:

```text
GAME_PAUSED GAME_RESUMED SAVE_REQUESTED SAVE_COMPLETED
LOAD_REQUESTED LOAD_COMPLETED WORLD_RESET
```

## 6. Snapshots, deltas and digest

`WORLD_SNAPSHOT` carries the complete bridge-visible gameplay state and a canonical SHA-256 digest. `WORLD_DELTA` carries ordered deterministic add/remove/replace operations, source/target world versions and the post-mutation digest.

Applying ordered deltas after a snapshot must reproduce the authoritative final state and digest. A sequence gap, wrong `from_world_version` or digest mismatch is a bridge-integrity failure.

## 7. Pause, cancellation and timeout

- paused worlds do not advance virtual time;
- new actions are rejected while paused;
- task cancellation increments task generation and cancels the task-owned active action once;
- late completion callbacks after cancellation are ignored;
- deadlines use virtual time and expiry applies no completion effect;
- provider failure is observational metadata and cannot corrupt authoritative gameplay state.

## 8. Save/load

Saves contain canonical gameplay state only: entities, world components, virtual time, active actions and remaining durations, scheduled events, task generation and deterministic counters. They exclude model clients, network requests, process IDs and wall-clock timestamps.

Load creates a new epoch, restores the digest and invalidates all pre-load decisions. Corrupted/incompatible saves fail before active-world mutation.

## 9. Reference transports

- `InMemoryTransport`: ordered deterministic test transport with explicit fault injection.
- `JsonlTraceTransport`: append-only canonical JSONL recording and replay.

No public network listener is implemented in v0.6.

## 10. Structured error codes

```text
PROTOCOL_VERSION_UNSUPPORTED SCHEMA_INVALID UNKNOWN_MESSAGE_KIND
DUPLICATE_MESSAGE_CONFLICT DUPLICATE_ACTION_CONFLICT
STALE_WORLD_EPOCH STALE_WORLD_VERSION STALE_TASK_GENERATION GAME_PAUSED
ACTOR_NOT_FOUND ACTOR_BUSY ACTION_NOT_SUPPORTED ACTION_PRECONDITION_FAILED
TARGET_GONE NO_PATH LOCKED CANCELLED_BY_PLAYER ACTION_TIMEOUT
SAVE_CORRUPTED SAVE_VERSION_UNSUPPORTED DELTA_SEQUENCE_GAP
STATE_DIGEST_MISMATCH PROVIDER_UNAVAILABLE INTERNAL_BRIDGE_ERROR
```

Errors are serialized data and do not rely only on free-form exception text.
