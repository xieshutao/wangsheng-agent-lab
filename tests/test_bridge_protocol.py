from __future__ import annotations

import pytest

from wangsheng.bridge.errors import BridgeErrorCode, BridgeProtocolError
from wangsheng.bridge.messages import BridgeMessage, MessageKind
from wangsheng.bridge.protocol import (
    PROTOCOL_VERSION,
    apply_json_operations,
    canonical_json,
    gameplay_digest,
    json_diff,
)


def message_payload() -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": "msg.test",
        "message_kind": "HEARTBEAT",
        "session_id": "session.test",
        "world_id": "world.test",
        "world_epoch": "epoch.0001",
        "world_version": 0,
        "sequence": 1,
        "virtual_time_ms": 0,
        "payload": {},
    }


def test_canonical_json_is_stable() -> None:
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert gameplay_digest({"b": 2, "a": 1}) == gameplay_digest({"a": 1, "b": 2})


def test_bridge_message_round_trip() -> None:
    message = BridgeMessage.from_dict(message_payload())
    assert message.message_kind is MessageKind.HEARTBEAT
    assert BridgeMessage.from_dict(message.to_dict()) == message


def test_bridge_message_rejects_unknown_field() -> None:
    payload = message_payload()
    payload["unexpected"] = True
    with pytest.raises(BridgeProtocolError) as exc:
        BridgeMessage.from_dict(payload)
    assert exc.value.code is BridgeErrorCode.SCHEMA_INVALID


def test_bridge_message_rejects_unknown_kind() -> None:
    payload = message_payload()
    payload["message_kind"] = "UNPUBLISHED_KIND"
    with pytest.raises(BridgeProtocolError) as exc:
        BridgeMessage.from_dict(payload)
    assert exc.value.code is BridgeErrorCode.UNKNOWN_MESSAGE_KIND


def test_json_diff_reconstructs_nested_state() -> None:
    before = {"a": 1, "nested": {"x": [1, 2], "remove": True}}
    after = {"a": 2, "nested": {"x": [1, 3]}, "added": "yes"}
    operations = json_diff(before, after)
    assert apply_json_operations(before, operations) == after
