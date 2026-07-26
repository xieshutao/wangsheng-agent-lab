from __future__ import annotations

from wangsheng.bridge.headless_world import HeadlessGameWorld
from wangsheng.bridge.messages import MessageKind
from wangsheng.bridge.transport import (
    InMemoryTransport,
    JsonlTraceTransport,
    replay_message_stream,
)


def test_in_memory_transport_supports_fault_injection() -> None:
    transport = InMemoryTransport()
    world = HeadlessGameWorld(transport=transport)
    first = world.emit_snapshot()
    second = world.record_dialogue_turn(text_hash="sha256:test")
    assert transport.receive() == first
    transport.reorder_next_two()  # only one remains; no-op
    assert transport.receive() == second
    transport.send(first)
    transport.duplicate()
    assert transport.receive() == first
    assert transport.receive() == first


def test_jsonl_trace_round_trip_and_replay(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = JsonlTraceTransport(path)
    world = HeadlessGameWorld(trace_transport=trace, retained_message_limit=100)
    world.emit_snapshot()
    world.request_action(
        action_id="trace.move",
        action_name="move_to",
        arguments={"target_id": "door.front"},
    )
    world.advance(1000)
    messages = trace.read_all()
    replay = replay_message_stream(messages)
    assert replay.passed
    assert replay.final_digest == world.state_digest()


def test_replay_detects_missing_sequence() -> None:
    world = HeadlessGameWorld(retained_message_limit=100)
    world.emit_snapshot()
    world.request_action(
        action_id="gap.move",
        action_name="move_to",
        arguments={"target_id": "door.front"},
    )
    world.advance(1000)
    messages = list(world.retained_messages)
    messages.pop(next(i for i, item in enumerate(messages) if item.message_kind is MessageKind.WORLD_DELTA))
    replay = replay_message_stream(messages)
    assert not replay.passed
    assert any("DELTA_SEQUENCE_GAP" in error for error in replay.errors)
