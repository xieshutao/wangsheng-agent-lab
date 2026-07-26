"""Deterministic headless game bridge for WangSheng Agent Lab v0.6."""

from .action_lifecycle import ActionLedger, ActionRecord, ActionStatus
from .adapter import HeadlessNpcAdapter
from .errors import BridgeErrorCode, BridgeProtocolError
from .headless_world import HeadlessGameWorld
from .messages import BridgeMessage, MessageKind
from .protocol import PROTOCOL_VERSION, canonical_json, gameplay_digest
from .scheduler import DeterministicScheduler, ScheduledEvent
from .transport import InMemoryTransport, JsonlTraceTransport, replay_message_stream

__all__ = [
    "ActionLedger",
    "ActionRecord",
    "ActionStatus",
    "BridgeErrorCode",
    "BridgeMessage",
    "BridgeProtocolError",
    "DeterministicScheduler",
    "HeadlessGameWorld",
    "HeadlessNpcAdapter",
    "InMemoryTransport",
    "JsonlTraceTransport",
    "MessageKind",
    "PROTOCOL_VERSION",
    "ScheduledEvent",
    "canonical_json",
    "gameplay_digest",
    "replay_message_stream",
]
