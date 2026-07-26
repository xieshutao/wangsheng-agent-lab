from __future__ import annotations

from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from .action_lifecycle import ActionLedger, ActionRecord, ActionStatus
from .errors import BridgeErrorCode, BridgeProtocolError
from .messages import BridgeMessage, MessageKind
from .protocol import PROTOCOL_VERSION, content_fingerprint, gameplay_digest, json_diff
from .savegame import SaveGame
from .scheduler import DeterministicScheduler, ScheduledEvent
from .transport import InMemoryTransport, JsonlTraceTransport


_ACTION_DURATIONS_MS: dict[str, int] = {
    "move_to": 1000,
    "observe": 500,
    "listen_at": 800,
    "ask_through": 1200,
    "report": 600,
    "open": 600,
    "close": 600,
}
_SUPPORTED_ACTIONS = frozenset({*_ACTION_DURATIONS_MS, "wait"})


@dataclass(slots=True)
class HeadlessGameWorld:
    session_id: str = "session.headless.v060"
    world_id: str = "world.front_hall.v060"
    transport: InMemoryTransport | None = None
    trace_transport: JsonlTraceTransport | None = None
    retained_message_limit: int = 2048
    request_cache_limit: int = 2048
    terminal_action_cache_limit: int = 256
    report_history_limit: int = 128
    heard_event_history_limit: int = 128
    world_epoch: str = "epoch.0001"
    world_version: int = 0
    task_generation: int = 1
    active_task_id: str | None = "task.bridge.reference"
    paused: bool = False
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    door: dict[str, Any] = field(default_factory=dict)
    observation_objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    facts: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    heard_events: list[str] = field(default_factory=list)
    scheduler: DeterministicScheduler = field(default_factory=DeterministicScheduler)
    actions: ActionLedger = field(default_factory=ActionLedger)
    _sequence: int = 0
    _message_counter: int = 0
    _epoch_counter: int = 1
    _event_counter: int = 0
    _retained_messages: deque[BridgeMessage] = field(init=False)
    _request_cache: OrderedDict[str, tuple[str, tuple[BridgeMessage, ...]]] = field(default_factory=OrderedDict)
    _mutation_count: int = 0

    def __post_init__(self) -> None:
        if self.retained_message_limit <= 0:
            raise ValueError("retained_message_limit must be positive")
        if self.request_cache_limit <= 0:
            raise ValueError("request_cache_limit must be positive")
        if self.terminal_action_cache_limit <= 0:
            raise ValueError("terminal_action_cache_limit must be positive")
        if self.report_history_limit <= 0:
            raise ValueError("report_history_limit must be positive")
        if self.heard_event_history_limit <= 0:
            raise ValueError("heard_event_history_limit must be positive")
        self._retained_messages = deque(maxlen=self.retained_message_limit)
        if not isinstance(self._request_cache, OrderedDict):
            self._request_cache = OrderedDict(self._request_cache)
        self.actions.terminal_cache_limit = self.terminal_action_cache_limit
        self.actions._prune_terminal_cache()
        self.reports = list(self.reports[-self.report_history_limit :])
        self.heard_events = list(self.heard_events[-self.heard_event_history_limit :])
        if not self.entities:
            self.entities = {
                "player": {
                    "entity_type": "player",
                    "location": "anchor.player",
                    "present": True,
                    "available": True,
                },
                "npc.qingyan": {
                    "entity_type": "npc",
                    "location": "anchor.player",
                    "present": True,
                    "available": True,
                },
                "visitor.xiaoman": {
                    "entity_type": "visitor",
                    "location": "anchor.outside_door",
                    "present": True,
                    "available": True,
                },
            }
        if not self.door:
            self.door = {
                "door_id": "door.front",
                "location": "anchor.door",
                "open": False,
                "locked": False,
                "reachable": True,
            }
        if not self.observation_objects:
            self.observation_objects = {
                "object.paper_crane": {
                    "object_type": "item",
                    "location": "anchor.counter",
                    "state": "intact",
                    "reachable": True,
                }
            }

    @property
    def virtual_time_ms(self) -> int:
        return self.scheduler.now_ms

    @property
    def retained_messages(self) -> tuple[BridgeMessage, ...]:
        return tuple(self._retained_messages)

    @property
    def mutation_count(self) -> int:
        return self._mutation_count

    def gameplay_state(self) -> dict[str, Any]:
        return {
            "virtual_time_ms": self.virtual_time_ms,
            "paused": self.paused,
            "entities": deepcopy(dict(sorted(self.entities.items()))),
            "door": deepcopy(self.door),
            "observation_objects": deepcopy(dict(sorted(self.observation_objects.items()))),
            "facts": deepcopy(self.facts),
            "reports": deepcopy(self.reports),
            "heard_events": list(self.heard_events),
            "active_actions": self.actions.active_to_dict(now_ms=self.virtual_time_ms),
            "scheduler": self.scheduler.snapshot(),
            "task_generation": self.task_generation,
            "active_task_id": self.active_task_id,
            "deterministic_counters": {
                "event_counter": self._event_counter,
            },
        }

    def state_digest(self) -> str:
        return gameplay_digest(self.gameplay_state())

    def emit_snapshot(self, *, causation_id: str | None = None) -> BridgeMessage:
        state = self.gameplay_state()
        return self._emit(
            MessageKind.WORLD_SNAPSHOT,
            payload={"state": state, "state_digest": gameplay_digest(state)},
            causation_id=causation_id,
        )

    def _next_message_id(self) -> str:
        self._message_counter += 1
        return f"msg.{self._message_counter:08d}"

    def _next_event_id(self, kind: str) -> str:
        self._event_counter += 1
        return f"event.{kind}.{self._event_counter:08d}"

    def _emit(
        self,
        kind: MessageKind,
        *,
        payload: dict[str, Any] | None = None,
        message_id: str | None = None,
        tick_id: str | None = None,
        task_id: str | None = None,
        action_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> BridgeMessage:
        self._sequence += 1
        message = BridgeMessage(
            protocol_version=PROTOCOL_VERSION,
            message_id=message_id or self._next_message_id(),
            message_kind=kind,
            session_id=self.session_id,
            world_id=self.world_id,
            world_epoch=self.world_epoch,
            world_version=self.world_version,
            sequence=self._sequence,
            tick_id=tick_id,
            task_id=task_id,
            action_id=action_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            virtual_time_ms=self.virtual_time_ms,
            payload=dict(payload or {}),
        )
        self._retained_messages.append(message)
        if self.transport is not None:
            self.transport.send(message)
        if self.trace_transport is not None:
            self.trace_transport.append(message)
        return message

    def _commit(
        self,
        reason: str,
        mutation: Callable[[], None],
        *,
        causation_id: str | None = None,
        action_id: str | None = None,
    ) -> BridgeMessage | None:
        before = self.gameplay_state()
        from_version = self.world_version
        mutation()
        after = self.gameplay_state()
        if before == after:
            return None
        self.world_version += 1
        self._mutation_count += 1
        operations = json_diff(before, after)
        return self._emit(
            MessageKind.WORLD_DELTA,
            payload={
                "from_world_version": from_version,
                "to_world_version": self.world_version,
                "operations": operations,
                "state_digest_after": gameplay_digest(after),
                "mutation_reason": reason,
            },
            causation_id=causation_id,
            action_id=action_id,
            task_id=self.active_task_id,
        )

    def make_message(
        self,
        kind: MessageKind,
        *,
        payload: dict[str, Any],
        message_id: str,
        task_id: str | None = None,
        tick_id: str | None = None,
        action_id: str | None = None,
    ) -> BridgeMessage:
        """Build an external request envelope without mutating the world."""
        return BridgeMessage(
            protocol_version=PROTOCOL_VERSION,
            message_id=message_id,
            message_kind=kind,
            session_id=self.session_id,
            world_id=self.world_id,
            world_epoch=self.world_epoch,
            world_version=self.world_version,
            sequence=0,
            tick_id=tick_id,
            task_id=task_id,
            action_id=action_id,
            virtual_time_ms=self.virtual_time_ms,
            payload=dict(payload),
        )

    def request_action(
        self,
        *,
        action_id: str,
        action_name: str,
        arguments: dict[str, Any] | None = None,
        actor_id: str = "npc.qingyan",
        message_id: str | None = None,
        task_id: str | None = None,
        tick_id: str | None = None,
        based_on_world_epoch: str | None = None,
        based_on_world_version: int | None = None,
        deadline_virtual_time_ms: int | None = None,
        task_generation: int | None = None,
    ) -> tuple[BridgeMessage, ...]:
        request = self.make_message(
            MessageKind.ACTION_REQUESTED,
            message_id=message_id or f"request.{action_id}",
            action_id=action_id,
            task_id=task_id or self.active_task_id,
            tick_id=tick_id,
            payload={
                "actor_id": actor_id,
                "action_name": action_name,
                "arguments": dict(arguments or {}),
                "based_on_world_epoch": based_on_world_epoch or self.world_epoch,
                "based_on_world_version": (
                    self.world_version
                    if based_on_world_version is None
                    else based_on_world_version
                ),
                "deadline_virtual_time_ms": deadline_virtual_time_ms,
                "task_generation": (
                    self.task_generation if task_generation is None else task_generation
                ),
            },
        )
        return self.handle(request)

    def handle(self, incoming: BridgeMessage) -> tuple[BridgeMessage, ...]:
        request_key = self._request_fingerprint(incoming)
        cached = self._request_cache.get(incoming.message_id)
        if cached is not None:
            cached_fingerprint, cached_responses = cached
            if cached_fingerprint != request_key:
                error = self._emit_protocol_error(
                    BridgeErrorCode.DUPLICATE_MESSAGE_CONFLICT,
                    "A message_id was reused with different request content.",
                    correlation_id=incoming.message_id,
                )
                return (error,)
            return cached_responses

        if incoming.session_id != self.session_id or incoming.world_id != self.world_id:
            response = self._emit_protocol_error(
                BridgeErrorCode.SCHEMA_INVALID,
                "Request session_id/world_id does not match the active bridge.",
                correlation_id=incoming.message_id,
            )
            self._remember_request(incoming.message_id, request_key, (response,))
            return (response,)

        normalized = self._emit(
            incoming.message_kind,
            payload=incoming.payload,
            message_id=incoming.message_id,
            tick_id=incoming.tick_id,
            task_id=incoming.task_id,
            action_id=incoming.action_id,
            correlation_id=incoming.correlation_id,
            causation_id=incoming.causation_id,
        )
        try:
            if normalized.message_kind is MessageKind.ACTION_REQUESTED:
                responses = self._process_action_request(normalized)
            elif normalized.message_kind is MessageKind.ACTION_CANCEL_REQUESTED:
                responses = self._process_action_cancel(normalized)
            elif normalized.message_kind is MessageKind.TASK_CANCELLED:
                responses = self.cancel_task(
                    reason=str(normalized.payload.get("reason", "player_cancelled")),
                    causation_id=normalized.message_id,
                )
            elif normalized.message_kind is MessageKind.GAME_PAUSED:
                responses = (self.pause(causation_id=normalized.message_id),)
            elif normalized.message_kind is MessageKind.GAME_RESUMED:
                responses = (self.resume(causation_id=normalized.message_id),)
            else:
                responses = (
                    self._emit_protocol_error(
                        BridgeErrorCode.UNKNOWN_MESSAGE_KIND,
                        f"Incoming {normalized.message_kind.value} is not a supported request kind.",
                        correlation_id=normalized.message_id,
                    ),
                )
        except BridgeProtocolError as exc:
            responses = (
                self._emit_protocol_error(
                    exc.code,
                    exc.message,
                    details=exc.details,
                    correlation_id=normalized.message_id,
                    action_id=normalized.action_id,
                ),
            )
        self._remember_request(incoming.message_id, request_key, tuple(responses))
        return tuple(responses)

    def _remember_request(
        self,
        message_id: str,
        fingerprint: str,
        responses: tuple[BridgeMessage, ...],
    ) -> None:
        self._request_cache[message_id] = (fingerprint, responses)
        self._request_cache.move_to_end(message_id)
        while len(self._request_cache) > self.request_cache_limit:
            self._request_cache.popitem(last=False)

    @property
    def request_cache_size(self) -> int:
        return len(self._request_cache)

    @staticmethod
    def _request_fingerprint(message: BridgeMessage) -> str:
        return content_fingerprint(
            {
                "protocol_version": message.protocol_version,
                "message_kind": message.message_kind.value,
                "session_id": message.session_id,
                "world_id": message.world_id,
                "world_epoch": message.world_epoch,
                "world_version": message.world_version,
                "tick_id": message.tick_id,
                "task_id": message.task_id,
                "action_id": message.action_id,
                "payload": message.payload,
            }
        )

    def _emit_protocol_error(
        self,
        code: BridgeErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        action_id: str | None = None,
    ) -> BridgeMessage:
        return self._emit(
            MessageKind.PROTOCOL_ERROR,
            payload={
                "error_code": code.value,
                "message": message,
                "details": dict(details or {}),
            },
            correlation_id=correlation_id,
            action_id=action_id,
        )

    def _process_action_request(self, request: BridgeMessage) -> tuple[BridgeMessage, ...]:
        payload = request.payload
        required = {
            "actor_id",
            "action_name",
            "arguments",
            "based_on_world_epoch",
            "based_on_world_version",
            "deadline_virtual_time_ms",
            "task_generation",
        }
        if set(payload) != required:
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "ACTION_REQUESTED payload fields do not match the v0.6 schema.",
                {
                    "missing": sorted(required - set(payload)),
                    "unknown": sorted(set(payload) - required),
                },
            )
        action_id = request.action_id
        if not action_id:
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "ACTION_REQUESTED requires action_id.",
            )
        actor_id = payload["actor_id"]
        action_name = payload["action_name"]
        arguments = payload["arguments"]
        if not isinstance(actor_id, str) or not isinstance(action_name, str):
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "actor_id and action_name must be strings.",
            )
        if not isinstance(arguments, dict):
            raise BridgeProtocolError(
                BridgeErrorCode.SCHEMA_INVALID,
                "arguments must be an object.",
            )
        record = ActionRecord(
            action_id=action_id,
            actor_id=actor_id,
            action_name=action_name,
            arguments=dict(arguments),
            based_on_world_epoch=str(payload["based_on_world_epoch"]),
            based_on_world_version=int(payload["based_on_world_version"]),
            deadline_virtual_time_ms=(
                None
                if payload["deadline_virtual_time_ms"] is None
                else int(payload["deadline_virtual_time_ms"])
            ),
            task_generation=int(payload["task_generation"]),
            task_id=request.task_id,
            tick_id=request.tick_id,
            requested_at_ms=self.virtual_time_ms,
        )
        existing = self.actions.get(action_id)
        if existing is not None:
            if existing.request_fingerprint() != record.request_fingerprint():
                raise BridgeProtocolError(
                    BridgeErrorCode.DUPLICATE_ACTION_CONFLICT,
                    f"Action ID {action_id!r} was reused with different content.",
                )
            return (self._emit_action_state(existing, request, duplicate=True),)

        rejection = self._validate_action(record)
        if rejection is not None:
            code, text = rejection
            non_mutating_rejections = {
                BridgeErrorCode.STALE_WORLD_EPOCH,
                BridgeErrorCode.STALE_WORLD_VERSION,
                BridgeErrorCode.STALE_TASK_GENERATION,
                BridgeErrorCode.GAME_PAUSED,
            }
            if code not in non_mutating_rejections:

                def reject_mutation() -> None:
                    self.actions.register(record)
                    self.actions.transition(
                        action_id,
                        ActionStatus.REJECTED,
                        now_ms=self.virtual_time_ms,
                        code=code.value,
                        payload={"message": text},
                    )

                self._commit(
                    "action_rejected",
                    reject_mutation,
                    causation_id=request.message_id,
                    action_id=action_id,
                )
            return (
                self._emit(
                    MessageKind.ACTION_REJECTED,
                    payload={"error_code": code.value, "message": text},
                    task_id=request.task_id,
                    tick_id=request.tick_id,
                    action_id=action_id,
                    correlation_id=request.message_id,
                    causation_id=request.message_id,
                ),
            )

        duration_ms = self._action_duration_ms(record)
        due_ms = self.virtual_time_ms + duration_ms

        def start_mutation() -> None:
            self.actions.register(record)
            self.actions.transition(action_id, ActionStatus.ACCEPTED, now_ms=self.virtual_time_ms)
            self.actions.transition(action_id, ActionStatus.STARTED, now_ms=self.virtual_time_ms)
            record.completion_due_ms = due_ms
            self.scheduler.schedule_at(
                event_id=f"action.{action_id}.complete",
                event_kind="action_complete",
                scheduled_time_ms=due_ms,
                priority=100,
                payload={"action_id": action_id},
            )
            if record.deadline_virtual_time_ms is not None:
                self.scheduler.schedule_at(
                    event_id=f"action.{action_id}.expire",
                    event_kind="action_expire",
                    scheduled_time_ms=record.deadline_virtual_time_ms,
                    priority=10,
                    payload={"action_id": action_id},
                )

        self._commit(
            "action_started",
            start_mutation,
            causation_id=request.message_id,
            action_id=action_id,
        )
        accepted = self._emit(
            MessageKind.ACTION_ACCEPTED,
            payload={"duration_ms": duration_ms, "completion_due_ms": due_ms},
            task_id=request.task_id,
            tick_id=request.tick_id,
            action_id=action_id,
            correlation_id=request.message_id,
            causation_id=request.message_id,
        )
        started = self._emit(
            MessageKind.ACTION_STARTED,
            payload={"started_at_ms": self.virtual_time_ms, "completion_due_ms": due_ms},
            task_id=request.task_id,
            tick_id=request.tick_id,
            action_id=action_id,
            correlation_id=request.message_id,
            causation_id=accepted.message_id,
        )
        return accepted, started

    def _emit_action_state(
        self,
        record: ActionRecord,
        request: BridgeMessage,
        *,
        duplicate: bool,
    ) -> BridgeMessage:
        mapping = {
            ActionStatus.REQUESTED: MessageKind.ACTION_REQUESTED,
            ActionStatus.ACCEPTED: MessageKind.ACTION_ACCEPTED,
            ActionStatus.STARTED: MessageKind.ACTION_STARTED,
            ActionStatus.REJECTED: MessageKind.ACTION_REJECTED,
            ActionStatus.COMPLETED: MessageKind.ACTION_COMPLETED,
            ActionStatus.FAILED: MessageKind.ACTION_FAILED,
            ActionStatus.CANCELLED: MessageKind.ACTION_CANCELLED,
            ActionStatus.EXPIRED: MessageKind.ACTION_EXPIRED,
        }
        return self._emit(
            mapping[record.status],
            payload={
                "duplicate": duplicate,
                "current_action_state": record.to_dict(now_ms=self.virtual_time_ms),
            },
            action_id=record.action_id,
            task_id=record.task_id,
            tick_id=record.tick_id,
            correlation_id=request.message_id,
            causation_id=request.message_id,
        )

    def _validate_action(
        self,
        record: ActionRecord,
    ) -> tuple[BridgeErrorCode, str] | None:
        if record.based_on_world_epoch != self.world_epoch:
            return BridgeErrorCode.STALE_WORLD_EPOCH, "Action was based on an old world epoch."
        if record.based_on_world_version != self.world_version:
            return BridgeErrorCode.STALE_WORLD_VERSION, "Action was based on an old world version."
        if record.task_generation != self.task_generation:
            return BridgeErrorCode.STALE_TASK_GENERATION, "Action was based on an old task generation."
        if self.paused:
            return BridgeErrorCode.GAME_PAUSED, "New actions are rejected while the game is paused."
        actor = self.entities.get(record.actor_id)
        if actor is None or not actor.get("present", False):
            return BridgeErrorCode.ACTOR_NOT_FOUND, "Actor does not exist in the active world."
        if not actor.get("available", True):
            return BridgeErrorCode.ACTOR_BUSY, "Actor is not available."
        active = self.actions.active_for_actor(record.actor_id)
        if active is not None:
            return BridgeErrorCode.ACTOR_BUSY, f"Actor already has active action {active.action_id}."
        if record.action_name not in _SUPPORTED_ACTIONS:
            return BridgeErrorCode.ACTION_NOT_SUPPORTED, "Action is not supported by v0.6 world."
        deadline = record.deadline_virtual_time_ms
        if deadline is not None and deadline <= self.virtual_time_ms:
            return BridgeErrorCode.ACTION_TIMEOUT, "Action deadline has already elapsed."
        return self._check_action_preconditions(record)

    def _check_action_preconditions(
        self,
        record: ActionRecord,
    ) -> tuple[BridgeErrorCode, str] | None:
        action = record.action_name
        arguments = record.arguments
        actor_location = self.entities[record.actor_id]["location"]
        if action == "move_to":
            target = arguments.get("target_id")
            if target not in {"player", "door.front", "object.paper_crane"}:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Unknown navigation target."
            if target == "door.front" and not self.door["reachable"]:
                return BridgeErrorCode.NO_PATH, "The path to the front door is blocked."
            if target == "object.paper_crane" and not self.observation_objects[target]["reachable"]:
                return BridgeErrorCode.NO_PATH, "The observation object is unreachable."
        elif action == "ask_through":
            if actor_location != "anchor.door":
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Actor must be at the door."
            if self.door["open"]:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Door must be closed."
            if not self.entities["visitor.xiaoman"]["present"]:
                return BridgeErrorCode.TARGET_GONE, "Visitor is no longer present."
            if arguments.get("topic") not in {"identity", "purpose", "request", "door_state"}:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Unsupported question topic."
        elif action == "listen_at":
            if actor_location != "anchor.door":
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Actor must be at the door."
        elif action == "report":
            if actor_location != self.entities["player"]["location"]:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Actor must be near player."
            fact_ids = arguments.get("fact_ids", [])
            if not isinstance(fact_ids, list) or not fact_ids:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Report requires fact_ids."
        elif action == "observe":
            target = arguments.get("target_id")
            if target not in {"door.front", "object.paper_crane", "visitor.xiaoman"}:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Unknown observation target."
            if target == "visitor.xiaoman" and not self.entities[target]["present"]:
                return BridgeErrorCode.TARGET_GONE, "Visitor is no longer present."
        elif action == "open":
            if self.door["locked"]:
                return BridgeErrorCode.LOCKED, "The front door is locked."
            if self.door["open"]:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Door is already open."
        elif action == "close":
            if not self.door["open"]:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "Door is already closed."
        elif action == "wait":
            duration = arguments.get("duration_ms")
            if not isinstance(duration, int) or not 0 <= duration <= 5000:
                return BridgeErrorCode.ACTION_PRECONDITION_FAILED, "wait duration_ms must be 0..5000."
        return None

    def _action_duration_ms(self, record: ActionRecord) -> int:
        if record.action_name == "wait":
            return int(record.arguments["duration_ms"])
        return _ACTION_DURATIONS_MS[record.action_name]

    def advance(self, delta_ms: int) -> tuple[BridgeMessage, ...]:
        if delta_ms < 0:
            raise ValueError("delta_ms must be non-negative.")
        if self.paused:
            return ()
        target = self.virtual_time_ms + delta_ms
        emitted_before = self._sequence
        while True:
            next_event = self.scheduler.peek()
            if next_event is None or next_event.scheduled_time_ms > target:
                break

            def pop_event() -> None:
                self.scheduler.pop_next()

            self._commit("scheduler_event_due", pop_event)
            self._handle_scheduled_event(next_event)
        if self.virtual_time_ms < target:

            def advance_clock() -> None:
                self.scheduler.set_now(target)

            self._commit("virtual_clock_advance", advance_clock)
        return tuple(message for message in self._retained_messages if message.sequence > emitted_before)

    def simulate_completion_callback(self, action_id: str) -> tuple[BridgeMessage, ...]:
        """Inject a completion callback for deterministic duplicate/late-callback tests."""
        before = self._sequence
        self._handle_scheduled_event(
            ScheduledEvent(
                self.virtual_time_ms,
                100,
                0,
                f"callback.{action_id}",
                "action_complete",
                {"action_id": action_id},
            )
        )
        return tuple(message for message in self._retained_messages if message.sequence > before)

    def _handle_scheduled_event(self, event: ScheduledEvent) -> None:
        if event.cancelled:
            return
        if event.event_kind == "world_event":
            self.apply_world_event(
                str(event.payload["event_name"]),
                dict(event.payload.get("event_payload", {})),
                scheduled_event_id=event.event_id,
            )
            return
        action_id = str(event.payload.get("action_id", ""))
        record = self.actions.get(action_id)
        if record is None or record.status.terminal:
            return
        if event.event_kind == "action_expire":
            self._terminal_action(
                record,
                ActionStatus.EXPIRED,
                BridgeErrorCode.ACTION_TIMEOUT.value,
                "Action expired before completion.",
            )
        elif event.event_kind == "action_complete":
            dynamic_failure = self._dynamic_completion_failure(record)
            if dynamic_failure is not None:
                code, message = dynamic_failure
                self._terminal_action(record, ActionStatus.FAILED, code.value, message)
            else:
                self._complete_action(record)

    def _dynamic_completion_failure(
        self,
        record: ActionRecord,
    ) -> tuple[BridgeErrorCode, str] | None:
        if record.task_generation != self.task_generation:
            return BridgeErrorCode.CANCELLED_BY_PLAYER, "Task generation changed before completion."
        if record.action_name == "move_to" and record.arguments.get("target_id") == "door.front":
            if not self.door["reachable"]:
                return BridgeErrorCode.NO_PATH, "Path became blocked before movement completed."
        if record.action_name == "ask_through" and not self.entities["visitor.xiaoman"]["present"]:
            return BridgeErrorCode.TARGET_GONE, "Visitor left before the question completed."
        return None

    def _complete_action(self, record: ActionRecord) -> None:
        evidence: dict[str, Any] = {}
        world_effect: dict[str, Any] = {}

        def completion_mutation() -> None:
            nonlocal evidence, world_effect
            self._cancel_action_events(record.action_id)
            action = record.action_name
            args = record.arguments
            if action == "move_to":
                target = args["target_id"]
                destination = {
                    "player": self.entities["player"]["location"],
                    "door.front": "anchor.door",
                    "object.paper_crane": self.observation_objects["object.paper_crane"]["location"],
                }[target]
                previous = self.entities[record.actor_id]["location"]
                self.entities[record.actor_id]["location"] = destination
                world_effect = {"actor.location": {"from": previous, "to": destination}}
            elif action == "observe":
                target = args["target_id"]
                if target == "door.front":
                    evidence = {
                        "target_id": target,
                        "open": self.door["open"],
                        "locked": self.door["locked"],
                        "reachable": self.door["reachable"],
                    }
                elif target == "visitor.xiaoman":
                    evidence = {"target_id": target, "present": True}
                else:
                    evidence = {"target_id": target, **self.observation_objects[target]}
            elif action == "listen_at":
                text = "A person is waiting outside the closed front door."
                if text not in self.heard_events:
                    self._append_heard_event(text)
                evidence = {"predicate": "presence", "value": "waiting_outside"}
            elif action == "ask_through":
                fact = self._fact_for_topic(str(args["topic"]))
                if fact not in self.facts:
                    self.facts.append(fact)
                evidence = dict(fact)
            elif action == "report":
                report = {
                    "fact_ids": list(args["fact_ids"]),
                    "tone": str(args.get("tone", "neutral")),
                    "rendered_by": "deterministic_fact_renderer",
                }
                self._append_report(report)
                evidence = dict(report)
            elif action == "open":
                self.door["open"] = True
                world_effect = {"door.open": {"from": False, "to": True}}
            elif action == "close":
                self.door["open"] = False
                world_effect = {"door.open": {"from": True, "to": False}}
            self.actions.transition(
                record.action_id,
                ActionStatus.COMPLETED,
                now_ms=self.virtual_time_ms,
                code="COMPLETED",
                payload={"evidence": evidence, "world_effect": world_effect},
            )

        self._commit(
            "action_completed",
            completion_mutation,
            action_id=record.action_id,
        )
        self._emit(
            MessageKind.ACTION_COMPLETED,
            payload={
                "result_code": "COMPLETED",
                "evidence": evidence,
                "world_effect": world_effect,
                "state_digest": self.state_digest(),
            },
            action_id=record.action_id,
            task_id=record.task_id,
            tick_id=record.tick_id,
        )

    def _append_report(self, report: dict[str, Any]) -> None:
        self.reports.append(deepcopy(report))
        if len(self.reports) > self.report_history_limit:
            del self.reports[: len(self.reports) - self.report_history_limit]

    def _append_heard_event(self, event: str) -> None:
        self.heard_events.append(event)
        if len(self.heard_events) > self.heard_event_history_limit:
            del self.heard_events[: len(self.heard_events) - self.heard_event_history_limit]

    def _fact_for_topic(self, topic: str) -> dict[str, Any]:
        fact_number = len(self.facts) + 1
        if topic == "identity":
            predicate, value = "claimed_name", "Xiaoman"
        elif topic == "purpose":
            predicate, value = "visit_purpose", "speak_with_player"
        elif topic == "request":
            predicate, value = "visitor_request", "notify_player_of_arrival"
        elif topic == "door_state":
            predicate, value = "door_state", "open" if self.door["open"] else "closed"
        else:  # guarded by preconditions
            predicate, value = topic, "unknown"
        return {
            "fact_id": f"fact.bridge.{predicate}.{fact_number:03d}",
            "subject": "door.front" if topic == "door_state" else "visitor.xiaoman",
            "predicate": predicate,
            "value": value,
            "source": "direct_observation" if topic == "door_state" else "visitor_statement",
            "certainty": "TRUE" if topic == "door_state" else "CLAIMED",
        }

    def _terminal_action(
        self,
        record: ActionRecord,
        status: ActionStatus,
        code: str,
        message: str,
    ) -> BridgeMessage:
        def terminal_mutation() -> None:
            self._cancel_action_events(record.action_id)
            self.actions.transition(
                record.action_id,
                status,
                now_ms=self.virtual_time_ms,
                code=code,
                payload={"message": message},
            )

        self._commit(
            f"action_{status.value.lower()}",
            terminal_mutation,
            action_id=record.action_id,
        )
        kind = {
            ActionStatus.FAILED: MessageKind.ACTION_FAILED,
            ActionStatus.CANCELLED: MessageKind.ACTION_CANCELLED,
            ActionStatus.EXPIRED: MessageKind.ACTION_EXPIRED,
            ActionStatus.REJECTED: MessageKind.ACTION_REJECTED,
        }[status]
        return self._emit(
            kind,
            payload={"error_code": code, "message": message},
            action_id=record.action_id,
            task_id=record.task_id,
            tick_id=record.tick_id,
        )

    def _cancel_action_events(self, action_id: str) -> None:
        self.scheduler.cancel(f"action.{action_id}.complete")
        self.scheduler.cancel(f"action.{action_id}.expire")

    def _process_action_cancel(self, request: BridgeMessage) -> tuple[BridgeMessage, ...]:
        action_id = request.action_id or str(request.payload.get("action_id", ""))
        record = self.actions.get(action_id)
        if record is None:
            return (
                self._emit_protocol_error(
                    BridgeErrorCode.ACTION_PRECONDITION_FAILED,
                    "Unknown action_id for cancellation.",
                    correlation_id=request.message_id,
                    action_id=action_id or None,
                ),
            )
        if record.status.terminal:
            return (self._emit_action_state(record, request, duplicate=True),)
        return (
            self._terminal_action(
                record,
                ActionStatus.CANCELLED,
                BridgeErrorCode.CANCELLED_BY_PLAYER.value,
                "Action was cancelled.",
            ),
        )

    def assign_task(self, task_id: str) -> BridgeMessage:
        def mutation() -> None:
            self.task_generation += 1
            self.active_task_id = task_id

        self._commit("task_assigned", mutation)
        return self._emit(
            MessageKind.TASK_ASSIGNED,
            payload={"task_generation": self.task_generation},
            task_id=task_id,
        )

    def cancel_task(
        self,
        *,
        reason: str = "player_cancelled",
        causation_id: str | None = None,
    ) -> tuple[BridgeMessage, ...]:
        previous_task = self.active_task_id
        active = self.actions.active_for_actor("npc.qingyan")

        def mutation() -> None:
            self.task_generation += 1
            self.active_task_id = None
            if active is not None and not active.status.terminal:
                self._cancel_action_events(active.action_id)
                self.actions.transition(
                    active.action_id,
                    ActionStatus.CANCELLED,
                    now_ms=self.virtual_time_ms,
                    code=BridgeErrorCode.CANCELLED_BY_PLAYER.value,
                    payload={"message": reason},
                )

        self._commit("task_cancelled", mutation, causation_id=causation_id)
        messages = [
            self._emit(
                MessageKind.TASK_CANCELLED,
                payload={"reason": reason, "task_generation": self.task_generation},
                task_id=previous_task,
                causation_id=causation_id,
            )
        ]
        if active is not None and active.status is ActionStatus.CANCELLED:
            messages.append(
                self._emit(
                    MessageKind.ACTION_CANCELLED,
                    payload={
                        "error_code": BridgeErrorCode.CANCELLED_BY_PLAYER.value,
                        "message": reason,
                    },
                    action_id=active.action_id,
                    task_id=active.task_id,
                    causation_id=messages[0].message_id,
                )
            )
        return tuple(messages)

    def pause(self, *, causation_id: str | None = None) -> BridgeMessage:
        self._commit("game_paused", lambda: setattr(self, "paused", True), causation_id=causation_id)
        return self._emit(
            MessageKind.GAME_PAUSED,
            payload={"paused": True},
            causation_id=causation_id,
        )

    def resume(self, *, causation_id: str | None = None) -> BridgeMessage:
        self._commit("game_resumed", lambda: setattr(self, "paused", False), causation_id=causation_id)
        return self._emit(
            MessageKind.GAME_RESUMED,
            payload={"paused": False, "requires_fresh_decision": True},
            causation_id=causation_id,
        )

    def schedule_world_event(
        self,
        *,
        event_name: str,
        delay_ms: int,
        payload: dict[str, Any] | None = None,
        priority: int = 50,
    ) -> str:
        event_id = self._next_event_id(event_name)

        def mutation() -> None:
            self.scheduler.schedule_after(
                event_id=event_id,
                event_kind="world_event",
                delay_ms=delay_ms,
                priority=priority,
                payload={"event_name": event_name, "event_payload": dict(payload or {})},
            )

        self._commit("world_event_scheduled", mutation)
        return event_id

    def apply_world_event(
        self,
        event_name: str,
        payload: dict[str, Any] | None = None,
        *,
        scheduled_event_id: str | None = None,
    ) -> BridgeMessage:
        payload = dict(payload or {})
        active = self.actions.active_for_actor("npc.qingyan")

        def mutation() -> None:
            if event_name == "path_reachable":
                self.door["reachable"] = bool(payload["reachable"])
                if (
                    not self.door["reachable"]
                    and active is not None
                    and active.action_name == "move_to"
                    and active.arguments.get("target_id") == "door.front"
                ):
                    self._cancel_action_events(active.action_id)
                    self.actions.transition(
                        active.action_id,
                        ActionStatus.FAILED,
                        now_ms=self.virtual_time_ms,
                        code=BridgeErrorCode.NO_PATH.value,
                        payload={"message": "Path became blocked during movement."},
                    )
            elif event_name == "door_locked":
                self.door["locked"] = bool(payload["locked"])
            elif event_name == "visitor_present":
                self.entities["visitor.xiaoman"]["present"] = bool(payload["present"])
                if (
                    not self.entities["visitor.xiaoman"]["present"]
                    and active is not None
                    and active.action_name == "ask_through"
                ):
                    self._cancel_action_events(active.action_id)
                    self.actions.transition(
                        active.action_id,
                        ActionStatus.FAILED,
                        now_ms=self.virtual_time_ms,
                        code=BridgeErrorCode.TARGET_GONE.value,
                        payload={"message": "Visitor left during question."},
                    )
            elif event_name == "player_move":
                self.entities["player"]["location"] = str(payload["location"])
            elif event_name == "provider_timeout":
                return
            else:
                raise BridgeProtocolError(
                    BridgeErrorCode.SCHEMA_INVALID,
                    f"Unsupported world event {event_name!r}.",
                )

        self._commit(
            f"world_event:{event_name}",
            mutation,
            causation_id=scheduled_event_id,
            action_id=active.action_id if active else None,
        )
        message = self._emit(
            MessageKind.WORLD_EVENT,
            payload={"event_name": event_name, "event_payload": payload},
            causation_id=scheduled_event_id,
        )
        if active is not None and active.status is ActionStatus.FAILED:
            self._emit(
                MessageKind.ACTION_FAILED,
                payload={
                    "error_code": active.terminal_code,
                    "message": active.terminal_payload.get("message", "Action interrupted."),
                },
                action_id=active.action_id,
                task_id=active.task_id,
                causation_id=message.message_id,
            )
        return message

    def record_dialogue_turn(self, *, text_hash: str, speaker: str = "player") -> BridgeMessage:
        """Record a dialogue-only turn without exposing tools or mutating gameplay state."""
        return self._emit(
            MessageKind.WORLD_EVENT,
            payload={
                "event_name": "dialogue_turn",
                "speaker": speaker,
                "text_hash": text_hash,
                "tools": [],
                "tool_choice": None,
                "world_mutated": False,
            },
        )

    def export_save(self) -> SaveGame:
        return SaveGame.create(world_id=self.world_id, gameplay_state=self.gameplay_state())

    def load_save(self, save: SaveGame | str | dict[str, Any]) -> tuple[BridgeMessage, BridgeMessage]:
        parsed = (
            save
            if isinstance(save, SaveGame)
            else SaveGame.from_json(save)
            if isinstance(save, str)
            else SaveGame.from_dict(save)
        )
        state = deepcopy(parsed.gameplay_state)
        self._epoch_counter += 1
        self.world_epoch = f"epoch.{self._epoch_counter:04d}"
        self.world_id = parsed.world_id
        self.world_version = 0
        self._request_cache.clear()
        self._restore_gameplay_state(state)
        completed = self._emit(
            MessageKind.LOAD_COMPLETED,
            payload={
                "restored_gameplay_digest": self.state_digest(),
                "new_world_epoch": self.world_epoch,
            },
        )
        snapshot = self.emit_snapshot(causation_id=completed.message_id)
        return completed, snapshot

    def _restore_gameplay_state(self, state: dict[str, Any]) -> None:
        self.paused = bool(state["paused"])
        self.entities = deepcopy(state["entities"])
        self.door = deepcopy(state["door"])
        self.observation_objects = deepcopy(state["observation_objects"])
        self.facts = deepcopy(state.get("facts", []))
        self.reports = deepcopy(state.get("reports", []))[-self.report_history_limit :]
        self.heard_events = list(state.get("heard_events", []))[-self.heard_event_history_limit :]
        self.actions = ActionLedger.from_state(
            active_payload=state.get("active_actions", {}),
            terminal_payload=None,
            terminal_cache_limit=self.terminal_action_cache_limit,
        )
        self.scheduler = DeterministicScheduler.from_snapshot(state["scheduler"])
        self.task_generation = int(state["task_generation"])
        self.active_task_id = state.get("active_task_id")
        counters = state.get("deterministic_counters", {})
        self._event_counter = int(counters.get("event_counter", 0))

    def reset(self) -> tuple[BridgeMessage, BridgeMessage]:
        fresh = HeadlessGameWorld(
            session_id=self.session_id,
            world_id=self.world_id,
            retained_message_limit=self.retained_message_limit,
            request_cache_limit=self.request_cache_limit,
            terminal_action_cache_limit=self.terminal_action_cache_limit,
            report_history_limit=self.report_history_limit,
            heard_event_history_limit=self.heard_event_history_limit,
        )
        self._epoch_counter += 1
        self.world_epoch = f"epoch.{self._epoch_counter:04d}"
        self.world_version = 0
        self._request_cache.clear()
        self._restore_gameplay_state(fresh.gameplay_state())
        reset_message = self._emit(
            MessageKind.WORLD_RESET,
            payload={"new_world_epoch": self.world_epoch},
        )
        return reset_message, self.emit_snapshot(causation_id=reset_message.message_id)
