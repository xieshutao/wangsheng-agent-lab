# UE ↔ WangSheng Slice Bridge Protocol v0.8

Transport: local HTTP, UTF-8 JSON, default `127.0.0.1:8765`.

## Create session

`POST /v0.8/session`

Returns the full public slice state.

## Command

`POST /v0.8/command`

```json
{
  "session_id": "slice-...",
  "action_id": "ue-000001",
  "command": "listen_at_door",
  "parameters": {}
}
```

The same `action_id` must return the same result and must not execute a second world transition.

## State

`GET /v0.8/session/{session_id}`

## Save/load

- `POST /v0.8/save` with `session_id` returns `payload_b64`.
- `POST /v0.8/load` with `payload_b64` restores a session after digest validation.

## UE implementation rule

UE must not assume a command succeeded because an animation played. It changes local quest/UI state only after a `SUCCESS` result from the service. Network errors are technical errors and must not be disguised as lore.
