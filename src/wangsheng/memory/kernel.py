from __future__ import annotations

import hashlib
import json
import re
import random
from collections import OrderedDict, defaultdict, deque
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .errors import MemoryErrorCode, MemoryKernelError
from .models import (
    UNKNOWN,
    AccessState,
    ArchiveReference,
    AcknowledgementOutcome,
    BranchResult,
    CanonicalEvent,
    Claim,
    ConflictType,
    ConnectionVersion,
    EmotionalResidue,
    ForgettingEvent,
    ForgettingMode,
    KernelConfig,
    ManifestationDelta,
    MemoryConflict,
    MemoryQueryResult,
    MemoryStateSnapshot,
    MemoryVersion,
    NameRecord,
    NameRecordDraft,
    Observation,
    ObservationDraft,
    PermissionLevel,
    Polarity,
    RecognitionScope,
    RecordStatus,
    ReplayVerification,
    SourceKind,
    StressSummary,
    VersionState,
    WorldAcknowledgement,
    freeze_value,
    primitive_value,
)


P1_NOT_IMPLEMENTED = "V0.7_P1_CONTRACT_ONLY"


_PERMISSION_RANK = {
    PermissionLevel.L1_WITNESS: 1,
    PermissionLevel.L2_BELONGING: 2,
    PermissionLevel.L3_LIMITED_CONTINUITY: 3,
    PermissionLevel.L4_PUBLIC_INSTITUTION: 4,
}

_PREDICATE_MIN_PERMISSION = {
    "SELF_IDENTIFIED_AS": PermissionLevel.L1_WITNESS,
    "HAS_OLD_CONNECTION_TO": PermissionLevel.L1_WITNESS,
    "HAS_NO_CLEAR_MEMORY_OF": PermissionLevel.L1_WITNESS,
    "WAS_KNOCKED": PermissionLevel.L1_WITNESS,
    "PROTECTED_VISITOR_OF": PermissionLevel.L2_BELONGING,
    "EXCLUSIVE_OCCUPANT_OF": PermissionLevel.L2_BELONGING,
    "SOLE_OFFICE_HOLDER_OF": PermissionLevel.L2_BELONGING,
    "CLAIMS_CAPACITY_SLOT_IN": PermissionLevel.L2_BELONGING,
    "CONTINUES_OLD_RESIDENT_CONNECTION": PermissionLevel.L3_LIMITED_CONTINUITY,
    "CURRENT_PERSON_USES_NAME_XIAOMAN": PermissionLevel.L3_LIMITED_CONTINUITY,
    "NAME_RECOGNIZED_HISTORY_UNRESOLVED": PermissionLevel.L3_LIMITED_CONTINUITY,
}

_L3_PREDICATES = {
    "CONTINUES_OLD_RESIDENT_CONNECTION",
    "CURRENT_PERSON_USES_NAME_XIAOMAN",
    "NAME_RECOGNIZED_HISTORY_UNRESOLVED",
}

_CONSENT_REQUIRED_PREDICATES = {
    "PROTECTED_VISITOR_OF",
    "EXCLUSIVE_OCCUPANT_OF",
    "SOLE_OFFICE_HOLDER_OF",
    "CLAIMS_CAPACITY_SLOT_IN",
    *_L3_PREDICATES,
}

_LOGICALLY_SINGLE_VALUED_PREDICATES = {
    "SELF_IDENTIFIED_AS",
    "PERMANENT_RESIDENT_OF",
    "CONTINUES_OLD_RESIDENT_CONNECTION",
    "CURRENT_PERSON_USES_NAME_XIAOMAN",
}

_CONFLICT_MITIGATIONS = {
    ConflictType.LOGICAL_EXCLUSION: (
        "PLAN_PROSPECTIVE_REPLACEMENT",
    ),
    ConflictType.PHYSICAL_EXCLUSIVITY: (
        "PLAN_REASSIGN_RESOURCE",
        "PLAN_PROSPECTIVE_REPLACEMENT",
    ),
    ConflictType.INSTITUTIONAL_EXCLUSIVITY: (
        "PLAN_TRANSFER_OFFICE",
        "PLAN_PROSPECTIVE_REPLACEMENT",
    ),
    ConflictType.DECLARED_CAPACITY_COMPETITION: (
        "PLAN_EXPAND_CAPACITY",
        "PLAN_RELEASE_CAPACITY",
        "PLAN_PROSPECTIVE_REPLACEMENT",
    ),
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        primitive_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _details(**values: Any) -> Mapping[str, Any]:
    return MappingProxyType(dict(values))


def _clamp_milli(value: int) -> int:
    return max(0, min(1000, value))


def _access_for_clarity(clarity_milli: int) -> AccessState:
    if clarity_milli >= 700:
        return AccessState.CLEAR
    if clarity_milli >= 300:
        return AccessState.FADED
    return AccessState.FORGOTTEN


def _value_is_visible(observed: Any, visible: Any) -> bool:
    """Return whether ``observed`` reveals no more than ``visible``.

    UNKNOWN is deliberately one-way: an observer may retain UNKNOWN when the
    visibility envelope contains a concrete value, but may not replace a visible
    UNKNOWN with a hidden concrete value.
    """

    from .models import UNKNOWN

    if observed == UNKNOWN:
        return True
    if visible == UNKNOWN:
        return observed == UNKNOWN
    if isinstance(observed, Mapping) and isinstance(visible, Mapping):
        return all(key in visible and _value_is_visible(value, visible[key]) for key, value in observed.items())
    if isinstance(observed, tuple) and isinstance(visible, tuple):
        return len(observed) == len(visible) and all(
            _value_is_visible(left, right) for left, right in zip(observed, visible, strict=True)
        )
    return observed == visible


def _claim_within_visibility(observed: Claim, visible: Claim) -> bool:
    return (
        observed.subject_id == visible.subject_id
        and observed.predicate == visible.predicate
        and _value_is_visible(observed.object_id_or_value, visible.object_id_or_value)
        and observed.time_scope == visible.time_scope
        and observed.recognition_scope == visible.recognition_scope
        and (observed.polarity == visible.polarity or observed.polarity.value == "UNKNOWN")
        and _value_is_visible(observed.qualifiers, visible.qualifiers)
    )


class MemoryVersioningKernel:
    """Deterministic v0.7 memory kernel, implemented incrementally.

    P2 owns occurrence facts, observations, immutable memory versions, memory
    state snapshots, forgetting transitions and rewrite lineage. P3-P5 methods
    deliberately keep the P1 marker until their respective phase.
    """

    def __init__(self, config: KernelConfig | None = None) -> None:
        self.config = config or KernelConfig()
        self._events: list[CanonicalEvent] = []
        self._events_by_id: dict[str, CanonicalEvent] = {}
        self._observations: list[Observation] = []
        self._observations_by_id: dict[str, Observation] = {}
        self._memory_versions: dict[str, MemoryVersion] = {}
        self._memory_states: dict[str, MemoryStateSnapshot] = {}
        self._lineage_versions: dict[str, list[str]] = defaultdict(list)
        self._forgetting_events: deque[ForgettingEvent] = deque(
            maxlen=self.config.recent_forgetting_events_cache
        )
        self._name_records: list[NameRecord] = []
        self._name_records_by_id: dict[str, NameRecord] = {}
        self._conflicts: list[MemoryConflict] = []
        self._conflicts_by_id: dict[str, MemoryConflict] = {}
        self._connection_versions: list[ConnectionVersion] = []
        self._connection_versions_by_id: dict[str, ConnectionVersion] = {}
        self._active_connection_version_ids: list[str] = []
        self._acknowledgements: deque[WorldAcknowledgement] = deque(
            maxlen=self.config.recent_acknowledgement_cache
        )
        self._acknowledgements_by_id: dict[str, WorldAcknowledgement] = {}
        self._manifestation_state: dict[str, Any] = {}
        self._manifestation_audit: deque[ManifestationDelta] = deque(
            maxlen=self.config.manifestation_audit_window
        )
        self._actor_lineages: dict[str, deque[str]] = defaultdict(deque)
        self._lineage_owner: dict[str, str] = {}
        self._belief_query_cache: dict[str, OrderedDict[str, MemoryQueryResult]] = defaultdict(OrderedDict)
        self._recent_archive_references: deque[ArchiveReference] = deque(
            maxlen=self.config.recent_forgetting_events_cache
        )
        self._archive_reference_total = 0
        self._archived_memory_versions = 0
        self._archived_memory_lineages = 0
        self._trace_sequences_by_object: dict[tuple[str, str], int] = {}
        self._history_trace: list[Mapping[str, Any]] = []
        self._id_counters: dict[str, int] = defaultdict(int)

    @staticmethod
    def _missing() -> None:
        raise NotImplementedError(P1_NOT_IMPLEMENTED)

    def _next_id(self, prefix: str) -> str:
        self._id_counters[prefix] += 1
        return f"{prefix}.v070.{self._id_counters[prefix]:08d}"

    def _append_trace(self, kind: str, payload: Mapping[str, Any]) -> int:
        sequence = len(self._history_trace) + 1
        self._history_trace.append(
            MappingProxyType(
                {
                    "sequence": sequence,
                    "kind": kind,
                    "payload": primitive_value(payload),
                }
            )
        )
        return sequence

    def _remember_trace_object(self, object_kind: str, object_id: str, sequence: int) -> None:
        self._trace_sequences_by_object[(object_kind, object_id)] = sequence

    def _archive_reference(
        self,
        *,
        object_kind: str,
        object_id: str,
        object_value: Any,
        reason: str,
        append_trace: bool = True,
        source_trace_sequence: int | None = None,
    ) -> ArchiveReference:
        sequence = source_trace_sequence or self._trace_sequences_by_object.pop(
            (object_kind, object_id), 0
        )
        if sequence <= 0:
            raise self._error(
                MemoryErrorCode.LIVE_STATE_BOUND_EXCEEDED,
                "cannot archive a live object without its append-only Trace reference",
                object_kind=object_kind,
                object_id=object_id,
            )
        reference = ArchiveReference(
            object_kind=object_kind,
            object_id=object_id,
            source_trace_sequence=sequence,
            object_digest=_sha256(object_value),
            archived_reason=reason,
        )
        self._recent_archive_references.append(reference)
        self._archive_reference_total += 1
        if object_kind == "MEMORY_VERSION":
            self._archived_memory_versions += 1
        elif object_kind == "MEMORY_LINEAGE":
            self._archived_memory_lineages += 1
        if append_trace:
            self._append_trace("LIVE_INDEX_EVICTED", {"archive_reference": reference})
        return reference

    @staticmethod
    def _archive_reference_from_data(data: Mapping[str, Any]) -> ArchiveReference:
        return ArchiveReference(
            object_kind=str(data["object_kind"]),
            object_id=str(data["object_id"]),
            source_trace_sequence=int(data["source_trace_sequence"]),
            object_digest=str(data["object_digest"]),
            archived_reason=str(data["archived_reason"]),
        )

    def _error(self, code: MemoryErrorCode, message: str, **details: Any) -> MemoryKernelError:
        return MemoryKernelError(code=code, message=message, details=_details(**details))

    def commit_event(
        self,
        *,
        world_tick: int,
        event_type: str,
        actor_ids: Sequence[str],
        target_ids: Sequence[str],
        location_id: str,
        payload: Mapping[str, Any],
        caused_by_action_id: str | None = None,
    ) -> CanonicalEvent:
        if world_tick < 0 or not event_type or not location_id:
            raise ValueError("world_tick, event_type and location_id must be valid")
        sequence = len(self._events) + 1
        event_id = self._next_id("event")
        digest_input = {
            "event_id": event_id,
            "sequence": sequence,
            "world_tick": world_tick,
            "event_type": event_type,
            "actor_ids": tuple(actor_ids),
            "target_ids": tuple(target_ids),
            "location_id": location_id,
            "payload": payload,
            "caused_by_action_id": caused_by_action_id,
            "schema_version": self.config.schema_version,
        }
        event = CanonicalEvent(
            event_id=event_id,
            sequence=sequence,
            world_tick=world_tick,
            event_type=event_type,
            actor_ids=tuple(actor_ids),
            target_ids=tuple(target_ids),
            location_id=location_id,
            payload=payload,
            caused_by_action_id=caused_by_action_id,
            schema_version=self.config.schema_version,
            event_digest=_sha256(digest_input),
        )
        self._events.append(event)
        self._events_by_id[event_id] = event
        self._append_trace("CANONICAL_EVENT_COMMITTED", {"event": event})
        return event

    def get_event(self, event_id: str) -> CanonicalEvent:
        try:
            return self._events_by_id[event_id]
        except KeyError as exc:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "canonical event does not exist",
                event_id=event_id,
            ) from exc

    def list_events(self) -> tuple[CanonicalEvent, ...]:
        return tuple(self._events)

    def replace_event(self, event_id: str, *, payload: Mapping[str, Any]) -> None:
        raise self._error(
            MemoryErrorCode.OCCURRENCE_MUTATION_FORBIDDEN,
            "canonical events are append-only; append a compensating event instead",
            event_id=event_id,
        )

    def delete_event(self, event_id: str) -> None:
        raise self._error(
            MemoryErrorCode.OCCURRENCE_MUTATION_FORBIDDEN,
            "canonical events cannot be deleted",
            event_id=event_id,
        )

    def occurrence_digest(self) -> str:
        return _sha256([event.event_digest for event in self._events])

    def record_observation(
        self,
        draft: ObservationDraft,
        *,
        visibility_claim: Claim,
    ) -> Observation:
        if not 0 <= draft.confidence_milli <= 1000:
            raise ValueError("confidence_milli must be within 0..1000")
        if not draft.source_family_id:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "observation requires a source family",
            )
        for event_id in draft.source_event_ids:
            self.get_event(event_id)
        for observation_id in draft.source_observation_ids:
            if observation_id not in self._observations_by_id:
                raise self._error(
                    MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                    "source observation does not exist",
                    observation_id=observation_id,
                )
        if not draft.source_event_ids and not draft.source_observation_ids and not draft.source_evidence_id:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "observation has no source",
            )
        if draft.source_kind == SourceKind.HEARD and not draft.source_actor_id:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "HEARD observation requires source_actor_id",
            )
        if draft.source_kind == SourceKind.HEARD and draft.source_event_ids and not any(
            self._events_by_id[event_id].event_type == "SPEECH" for event_id in draft.source_event_ids
        ):
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "HEARD observation must cite a SPEECH event",
                source_event_ids=draft.source_event_ids,
            )
        if draft.source_kind == SourceKind.INFERRED:
            input_count = len(draft.source_event_ids) + len(draft.source_observation_ids)
            if input_count < 2 and not draft.inference_rule_id:
                raise self._error(
                    MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                    "INFERRED observation requires two sources or inference_rule_id",
                )
        if draft.source_kind == SourceKind.MANIFESTED and not draft.derived_from_acknowledgement_id:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "MANIFESTED observation requires acknowledgement provenance",
            )
        if draft.source_kind == SourceKind.MANIFESTED and not draft.source_family_id.startswith("FAMILY_DERIVED_"):
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "MANIFESTED observation requires a derived evidence family",
                source_family_id=draft.source_family_id,
            )
        if not _claim_within_visibility(draft.claim, visibility_claim):
            raise self._error(
                MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK,
                "observation exceeds the authorized visibility claim",
                observer_id=draft.observer_id,
                source_event_ids=draft.source_event_ids,
            )

        observation = Observation(
            observation_id=self._next_id("observation"),
            observer_id=draft.observer_id,
            source_kind=draft.source_kind,
            source_event_ids=draft.source_event_ids,
            source_observation_ids=draft.source_observation_ids,
            source_actor_id=draft.source_actor_id,
            source_evidence_id=draft.source_evidence_id,
            source_family_id=draft.source_family_id,
            claim=draft.claim,
            confidence_milli=draft.confidence_milli,
            acquired_tick=draft.acquired_tick,
            world_version_seen=draft.world_version_seen,
            derived_from_acknowledgement_id=draft.derived_from_acknowledgement_id,
            inference_rule_id=draft.inference_rule_id,
        )
        self._observations.append(observation)
        self._observations_by_id[observation.observation_id] = observation
        self._append_trace("OBSERVATION_RECORDED", {"observation": observation})
        return observation

    def _validated_observations(
        self,
        *,
        owner_id: str,
        observation_ids: Sequence[str],
    ) -> tuple[Observation, ...]:
        if not observation_ids:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory version requires at least one observation",
                owner_id=owner_id,
            )
        observations: list[Observation] = []
        for observation_id in observation_ids:
            observation = self._observations_by_id.get(observation_id)
            if observation is None:
                raise self._error(
                    MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                    "memory references an unknown observation",
                    observation_id=observation_id,
                )
            if observation.observer_id != owner_id:
                raise self._error(
                    MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK,
                    "memory owner cannot consume another actor's private observation",
                    owner_id=owner_id,
                    observer_id=observation.observer_id,
                    observation_id=observation_id,
                )
            observations.append(observation)
        return tuple(observations)

    def _validate_lineage_request(
        self,
        *,
        owner_id: str,
        memory_lineage_id: str | None,
        parent_version_ids: Sequence[str],
    ) -> tuple[str, int, tuple[str, ...]]:
        parents = tuple(parent_version_ids)
        if memory_lineage_id is None:
            if parents:
                raise self._error(
                    MemoryErrorCode.MEMORY_LINEAGE_CYCLE,
                    "a new lineage cannot cite parents from an unspecified lineage",
                    parent_version_ids=parents,
                )
            return self._next_id("memory-lineage"), 1, parents

        known_versions = self._lineage_versions.get(memory_lineage_id, [])
        if not known_versions:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory lineage does not exist; omit memory_lineage_id to create a new lineage",
                memory_lineage_id=memory_lineage_id,
                parent_version_ids=parents,
            )

        for parent_id in parents:
            parent = self._memory_versions.get(parent_id)
            if parent is None or parent.memory_lineage_id != memory_lineage_id:
                raise self._error(
                    MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                    "parent memory is missing or belongs to another lineage",
                    parent_version_id=parent_id,
                    memory_lineage_id=memory_lineage_id,
                )
            if parent.owner_id != owner_id:
                raise self._error(
                    MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK,
                    "memory lineage owner mismatch",
                    parent_owner_id=parent.owner_id,
                    requested_owner_id=owner_id,
                )
        if len(set(parents)) != len(parents):
            raise self._error(
                MemoryErrorCode.MEMORY_LINEAGE_CYCLE,
                "duplicate parent versions are not allowed",
                parent_version_ids=parents,
            )
        next_version = max(self._memory_versions[item].version_no for item in known_versions) + 1
        return memory_lineage_id, next_version, parents

    def _invalidate_belief_cache(self, memory_version_id: str) -> None:
        for cache in self._belief_query_cache.values():
            cache.pop(memory_version_id, None)

    def _archive_live_memory_version(self, memory_version_id: str, *, reason: str) -> None:
        version = self._memory_versions.pop(memory_version_id, None)
        state = self._memory_states.pop(memory_version_id, None)
        if version is None or state is None:
            return
        lineage_ids = self._lineage_versions.get(version.memory_lineage_id)
        if lineage_ids is not None and memory_version_id in lineage_ids:
            lineage_ids.remove(memory_version_id)
        self._invalidate_belief_cache(memory_version_id)
        self._archive_reference(
            object_kind="MEMORY_VERSION",
            object_id=memory_version_id,
            object_value={"memory_version": version, "state": state},
            reason=reason,
        )

    def _archive_live_memory_lineage(self, memory_lineage_id: str, *, reason: str) -> None:
        owner_id = self._lineage_owner.get(memory_lineage_id)
        version_ids = tuple(self._lineage_versions.get(memory_lineage_id, ()))
        for memory_version_id in version_ids:
            self._archive_live_memory_version(memory_version_id, reason=reason)
        self._lineage_versions.pop(memory_lineage_id, None)
        self._lineage_owner.pop(memory_lineage_id, None)
        if owner_id is not None:
            actor_lineages = self._actor_lineages.get(owner_id)
            if actor_lineages is not None and memory_lineage_id in actor_lineages:
                actor_lineages.remove(memory_lineage_id)
            if actor_lineages is not None and not actor_lineages:
                self._actor_lineages.pop(owner_id, None)
        source_sequence = self._trace_sequences_by_object.pop(("MEMORY_LINEAGE", memory_lineage_id), 0)
        if source_sequence <= 0 and version_ids:
            source_sequence = next(
                (
                    reference.source_trace_sequence
                    for reference in reversed(self._recent_archive_references)
                    if reference.object_kind == "MEMORY_VERSION"
                    and reference.object_id in version_ids
                ),
                0,
            )
        if source_sequence > 0:
            self._archive_reference(
                object_kind="MEMORY_LINEAGE",
                object_id=memory_lineage_id,
                object_value={"owner_id": owner_id, "version_ids": version_ids},
                reason=reason,
                source_trace_sequence=source_sequence,
            )

    def _enforce_memory_bounds(self, *, owner_id: str, memory_lineage_id: str) -> None:
        lineage_ids = self._lineage_versions.get(memory_lineage_id, [])
        while len(lineage_ids) > self.config.active_memory_versions_per_lineage:
            self._archive_live_memory_version(
                lineage_ids[0],
                reason="ACTIVE_MEMORY_VERSIONS_PER_LINEAGE_BOUND",
            )
            lineage_ids = self._lineage_versions.get(memory_lineage_id, [])

        actor_lineages = self._actor_lineages[owner_id]
        while len(actor_lineages) > self.config.active_memory_lineages_per_actor:
            oldest_lineage_id = actor_lineages[0]
            if oldest_lineage_id == memory_lineage_id and len(actor_lineages) > 1:
                actor_lineages.rotate(-1)
                oldest_lineage_id = actor_lineages[0]
            self._archive_live_memory_lineage(
                oldest_lineage_id,
                reason="ACTIVE_MEMORY_LINEAGES_PER_ACTOR_BOUND",
            )
            actor_lineages = self._actor_lineages.get(owner_id, deque())

    def _archived_memory_version_from_trace(self, memory_version_id: str) -> MemoryVersion | None:
        for raw_record in reversed(self._history_trace):
            if raw_record["kind"] != "MEMORY_VERSION_CREATED":
                continue
            data = raw_record["payload"]["memory_version"]
            if data["memory_version_id"] == memory_version_id:
                return self._memory_version_from_data(data)
        return None

    def _archived_memory_state_from_trace(self, memory_version_id: str) -> MemoryStateSnapshot | None:
        state: MemoryStateSnapshot | None = None
        for raw_record in self._history_trace:
            kind = raw_record["kind"]
            payload = raw_record["payload"]
            if kind == "MEMORY_VERSION_CREATED":
                data = payload["state"]
                if data["memory_version_id"] == memory_version_id:
                    state = self._memory_state_from_data(data)
            elif state is not None and kind == "MEMORY_VERSION_REWRITTEN":
                if payload["parent_memory_version_id"] == memory_version_id:
                    state = replace(
                        state,
                        state_revision=state.state_revision + 1,
                        version_state=VersionState.REWRITTEN,
                        last_transition_event_id=f"memory-rewritten-by:{payload['new_memory_version_id']}",
                        last_transition_tick=self._archived_memory_version_from_trace(
                            payload["new_memory_version_id"]
                        ).created_tick,
                    )
            elif state is not None and kind == "FORGETTING_EVENT_APPLIED":
                data = payload["new_state"]
                if data["memory_version_id"] == memory_version_id:
                    state = self._memory_state_from_data(data)
            elif state is not None and kind == "MEMORY_CONTRADICTION_REGISTERED":
                ids = tuple(payload["memory_version_ids"])
                if memory_version_id in ids:
                    index = ids.index(memory_version_id)
                    detected_tick = int(payload["detected_tick"])
                    state = replace(
                        state,
                        state_revision=state.state_revision + 1,
                        version_state=VersionState.CONTRADICTED,
                        last_transition_event_id=f"memory-contradiction:{detected_tick}:{index + 1}",
                        last_transition_tick=detected_tick,
                    )
        return state

    def _create_memory_version(
        self,
        *,
        owner_id: str,
        observation_ids: Sequence[str],
        claim: Claim,
        source_kind: SourceKind,
        initial_clarity_milli: int,
        initial_emotion_residue: Sequence[EmotionalResidue],
        created_tick: int,
        memory_lineage_id: str | None,
        parent_version_ids: Sequence[str],
        rewrite_reason_code: str | None,
        allow_derived_claim: bool = False,
    ) -> MemoryVersion:
        if not 0 <= initial_clarity_milli <= 1000:
            raise ValueError("initial_clarity_milli must be within 0..1000")
        observations = self._validated_observations(owner_id=owner_id, observation_ids=observation_ids)
        if (
            source_kind != SourceKind.INFERRED
            and not allow_derived_claim
            and not any(observation.source_kind == source_kind for observation in observations)
        ):
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory source_kind is not represented by its observations",
                source_kind=source_kind,
                observation_ids=tuple(observation_ids),
            )
        if source_kind != SourceKind.INFERRED and not allow_derived_claim and not any(
            _claim_within_visibility(claim, observation.claim)
            and _claim_within_visibility(observation.claim, claim)
            for observation in observations
        ):
            raise self._error(
                MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK,
                "non-inferred memory claim is unsupported by its observations",
                owner_id=owner_id,
                observation_ids=tuple(observation_ids),
            )
        lineage_id, version_no, parents = self._validate_lineage_request(
            owner_id=owner_id,
            memory_lineage_id=memory_lineage_id,
            parent_version_ids=parent_version_ids,
        )
        memory_version_id = self._next_id("memory-version")
        normalized_residue = tuple(
            residue
            if residue.origin_memory_version_id is not None
            else replace(residue, origin_memory_version_id=memory_version_id)
            for residue in initial_emotion_residue
        )
        version = MemoryVersion(
            memory_lineage_id=lineage_id,
            memory_version_id=memory_version_id,
            version_no=version_no,
            owner_id=owner_id,
            parent_version_ids=parents,
            observation_ids=tuple(observation_ids),
            claim=claim,
            source_kind=source_kind,
            initial_clarity_milli=initial_clarity_milli,
            initial_emotion_residue=normalized_residue,
            created_tick=created_tick,
            rewrite_reason_code=rewrite_reason_code,
        )
        state = MemoryStateSnapshot(
            memory_version_id=memory_version_id,
            state_revision=1,
            access_state=_access_for_clarity(initial_clarity_milli),
            version_state=VersionState.ACTIVE,
            clarity_milli=initial_clarity_milli,
            emotion_residue=normalized_residue,
            last_transition_event_id=f"memory-created:{memory_version_id}",
            last_transition_tick=created_tick,
        )
        is_new_lineage = lineage_id not in self._lineage_owner
        self._memory_versions[memory_version_id] = version
        self._memory_states[memory_version_id] = state
        self._lineage_versions[lineage_id].append(memory_version_id)
        if is_new_lineage:
            self._lineage_owner[lineage_id] = owner_id
            self._actor_lineages[owner_id].append(lineage_id)
        trace_sequence = self._append_trace(
            "MEMORY_VERSION_CREATED",
            {"memory_version": version, "state": state},
        )
        self._remember_trace_object("MEMORY_VERSION", memory_version_id, trace_sequence)
        if is_new_lineage:
            self._remember_trace_object("MEMORY_LINEAGE", lineage_id, trace_sequence)
        return version

    def create_memory(
        self,
        *,
        owner_id: str,
        observation_ids: Sequence[str],
        claim: Claim,
        source_kind: SourceKind,
        initial_clarity_milli: int,
        initial_emotion_residue: Sequence[EmotionalResidue],
        created_tick: int,
        memory_lineage_id: str | None = None,
        parent_version_ids: Sequence[str] = (),
        rewrite_reason_code: str | None = None,
    ) -> MemoryVersion:
        version = self._create_memory_version(
            owner_id=owner_id,
            observation_ids=observation_ids,
            claim=claim,
            source_kind=source_kind,
            initial_clarity_milli=initial_clarity_milli,
            initial_emotion_residue=initial_emotion_residue,
            created_tick=created_tick,
            memory_lineage_id=memory_lineage_id,
            parent_version_ids=parent_version_ids,
            rewrite_reason_code=rewrite_reason_code,
            allow_derived_claim=False,
        )
        self._enforce_memory_bounds(
            owner_id=owner_id,
            memory_lineage_id=version.memory_lineage_id,
        )
        return version

    def rewrite_memory(
        self,
        *,
        memory_lineage_id: str,
        parent_version_ids: Sequence[str],
        observation_ids: Sequence[str],
        claim: Claim,
        source_kind: SourceKind,
        initial_clarity_milli: int,
        initial_emotion_residue: Sequence[EmotionalResidue],
        created_tick: int,
        rewrite_reason_code: str,
    ) -> MemoryVersion:
        parents = tuple(parent_version_ids)
        if not parents or not rewrite_reason_code:
            raise self._error(
                MemoryErrorCode.MEMORY_INVALID_TRANSITION,
                "rewrite requires parent versions and a reason code",
            )
        if source_kind == SourceKind.MANIFESTED and not rewrite_reason_code.startswith("WORLD_ACK_"):
            raise self._error(
                MemoryErrorCode.MEMORY_INVALID_TRANSITION,
                "MANIFESTED rewrite requires a WORLD_ACK_ reason code",
                rewrite_reason_code=rewrite_reason_code,
            )
        first_parent = self._memory_versions.get(parents[0])
        if first_parent is None:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "rewrite parent does not exist",
                parent_version_id=parents[0],
            )
        # Validate all inputs before mutating parent states.
        self._validated_observations(owner_id=first_parent.owner_id, observation_ids=observation_ids)
        self._validate_lineage_request(
            owner_id=first_parent.owner_id,
            memory_lineage_id=memory_lineage_id,
            parent_version_ids=parents,
        )
        version = self._create_memory_version(
            owner_id=first_parent.owner_id,
            observation_ids=observation_ids,
            claim=claim,
            source_kind=source_kind,
            initial_clarity_milli=initial_clarity_milli,
            initial_emotion_residue=initial_emotion_residue,
            created_tick=created_tick,
            memory_lineage_id=memory_lineage_id,
            parent_version_ids=parents,
            rewrite_reason_code=rewrite_reason_code,
            allow_derived_claim=source_kind == SourceKind.MANIFESTED,
        )
        for parent_id in parents:
            old = self._memory_states[parent_id]
            rewritten = replace(
                old,
                state_revision=old.state_revision + 1,
                version_state=VersionState.REWRITTEN,
                last_transition_event_id=f"memory-rewritten-by:{version.memory_version_id}",
                last_transition_tick=created_tick,
            )
            self._memory_states[parent_id] = rewritten
            self._invalidate_belief_cache(parent_id)
            self._append_trace(
                "MEMORY_VERSION_REWRITTEN",
                {"parent_memory_version_id": parent_id, "new_memory_version_id": version.memory_version_id},
            )
        self._enforce_memory_bounds(
            owner_id=first_parent.owner_id,
            memory_lineage_id=memory_lineage_id,
        )
        return version

    def transition_memory(
        self,
        memory_version_id: str,
        *,
        mode: ForgettingMode,
        reason_code: str,
        decay_per_night_milli: int,
        explicit_penalty_milli: int,
        explicit_rehearsal_bonus_milli: int,
        world_tick: int,
    ) -> MemoryStateSnapshot:
        previous = self._memory_states.get(memory_version_id)
        if previous is None:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory state does not exist",
                memory_version_id=memory_version_id,
            )
        if min(decay_per_night_milli, explicit_penalty_milli, explicit_rehearsal_bonus_milli) < 0:
            raise ValueError("memory transition values must be non-negative")
        if mode == ForgettingMode.UNSUPPRESS and previous.access_state != AccessState.SUPPRESSED:
            raise self._error(
                MemoryErrorCode.MEMORY_INVALID_TRANSITION,
                "UNSUPPRESS requires a suppressed memory",
                memory_version_id=memory_version_id,
            )

        new_clarity = _clamp_milli(
            previous.clarity_milli
            - decay_per_night_milli
            - explicit_penalty_milli
            + explicit_rehearsal_bonus_milli
        )
        if mode == ForgettingMode.SUPPRESS:
            new_access = AccessState.SUPPRESSED
        elif mode == ForgettingMode.UNSUPPRESS:
            new_access = _access_for_clarity(new_clarity)
        elif previous.access_state in (AccessState.SUPPRESSED, AccessState.SEALED):
            new_access = previous.access_state
        else:
            new_access = _access_for_clarity(new_clarity)

        if mode == ForgettingMode.FACT_AND_EMOTION:
            new_residue: tuple[EmotionalResidue, ...] = ()
        elif mode in (ForgettingMode.FACT_ONLY, ForgettingMode.REWRITE_WITH_RESIDUE):
            residue_items: list[EmotionalResidue] = []
            for item in previous.emotion_residue:
                if new_access == AccessState.FORGOTTEN and not item.access_independent:
                    continue
                intensity = max(0, item.intensity_milli - item.decay_per_night_milli)
                if intensity > 0:
                    residue_items.append(replace(item, intensity_milli=intensity))
            new_residue = tuple(residue_items)
        else:
            new_residue = previous.emotion_residue

        forgetting_event_id = self._next_id("forgetting-event")
        new_state = MemoryStateSnapshot(
            memory_version_id=memory_version_id,
            state_revision=previous.state_revision + 1,
            access_state=new_access,
            version_state=previous.version_state,
            clarity_milli=new_clarity,
            emotion_residue=new_residue,
            last_transition_event_id=forgetting_event_id,
            last_transition_tick=world_tick,
        )
        forgetting_event = ForgettingEvent(
            forgetting_event_id=forgetting_event_id,
            target_memory_version_id=memory_version_id,
            previous_state_revision=previous.state_revision,
            new_state_revision=new_state.state_revision,
            mode=mode,
            reason_code=reason_code,
            before_clarity_milli=previous.clarity_milli,
            after_clarity_milli=new_clarity,
            before_access_state=previous.access_state,
            after_access_state=new_access,
            emotion_deltas=new_residue,
            world_tick=world_tick,
        )
        self._memory_states[memory_version_id] = new_state
        self._invalidate_belief_cache(memory_version_id)
        self._forgetting_events.append(forgetting_event)
        self._append_trace(
            "FORGETTING_EVENT_APPLIED",
            {"forgetting_event": forgetting_event, "new_state": new_state},
        )
        return new_state

    def get_memory_version(self, memory_version_id: str) -> MemoryVersion:
        version = self._memory_versions.get(memory_version_id)
        if version is None:
            version = self._archived_memory_version_from_trace(memory_version_id)
        if version is None:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory version does not exist",
                memory_version_id=memory_version_id,
            )
        return version

    def get_memory_state(self, memory_version_id: str) -> MemoryStateSnapshot:
        state = self._memory_states.get(memory_version_id)
        if state is None:
            state = self._archived_memory_state_from_trace(memory_version_id)
        if state is None:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory state does not exist",
                memory_version_id=memory_version_id,
            )
        return state

    def list_forgetting_events(self) -> tuple[ForgettingEvent, ...]:
        return tuple(self._forgetting_events)

    def query_memory(self, memory_version_id: str) -> MemoryQueryResult:
        version = self.get_memory_version(memory_version_id)
        cache = self._belief_query_cache[version.owner_id]
        cached = cache.get(memory_version_id)
        if cached is not None:
            cache.move_to_end(memory_version_id)
            return cached
        state = self.get_memory_state(memory_version_id)
        accessible = state.access_state in (AccessState.CLEAR, AccessState.FADED)
        residues = state.emotion_residue
        if state.access_state == AccessState.FORGOTTEN:
            residues = tuple(item for item in residues if item.access_independent)
        result = MemoryQueryResult(
            memory_version_id=memory_version_id,
            access_state=state.access_state,
            version_state=state.version_state,
            claim=version.claim if accessible else None,
            emotion_residue=residues,
        )
        cache[memory_version_id] = result
        cache.move_to_end(memory_version_id)
        while len(cache) > self.config.belief_query_cache_per_actor:
            cache.popitem(last=False)
        return result

    def register_contradiction(
        self,
        memory_version_ids: Sequence[str],
        *,
        detected_tick: int,
    ) -> tuple[MemoryStateSnapshot, ...]:
        ids = tuple(memory_version_ids)
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise self._error(
                MemoryErrorCode.CONFLICT_UNSUPPORTED_TYPE,
                "contradiction requires at least two distinct memory versions",
                memory_version_ids=ids,
            )
        versions = tuple(self.get_memory_version(item) for item in ids)
        owner_ids = {item.owner_id for item in versions}
        if len(owner_ids) != 1:
            raise self._error(
                MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK,
                "contradiction registration is actor-local",
                memory_version_ids=ids,
                owner_ids=tuple(sorted(owner_ids)),
            )
        anchor = versions[0].claim
        for version in versions[1:]:
            if not self._claims_logically_exclusive(anchor, version.claim):
                raise self._error(
                    MemoryErrorCode.CONFLICT_UNSUPPORTED_TYPE,
                    "memory claims are not logically exclusive",
                    memory_version_ids=ids,
                )
        previous_states = tuple(self.get_memory_state(item) for item in ids)
        if all(state.version_state == VersionState.CONTRADICTED for state in previous_states):
            return previous_states
        if any(state.version_state != VersionState.ACTIVE for state in previous_states):
            raise self._error(
                MemoryErrorCode.MEMORY_INVALID_TRANSITION,
                "only active memory versions can enter a new contradiction set",
                memory_version_ids=ids,
                version_states=tuple(state.version_state for state in previous_states),
            )
        updated_states = tuple(
            replace(
                state,
                state_revision=state.state_revision + 1,
                version_state=VersionState.CONTRADICTED,
                last_transition_event_id=f"memory-contradiction:{detected_tick}:{index + 1}",
                last_transition_tick=detected_tick,
            )
            for index, state in enumerate(previous_states)
        )
        for state in updated_states:
            self._memory_states[state.memory_version_id] = state
        self._append_trace(
            "MEMORY_CONTRADICTION_REGISTERED",
            {"memory_version_ids": ids, "detected_tick": detected_tick},
        )
        return updated_states

    @staticmethod
    def _claims_logically_exclusive(left: Claim, right: Claim) -> bool:
        if (
            left.subject_id != right.subject_id
            or left.predicate != right.predicate
            or left.time_scope != right.time_scope
            or left.recognition_scope != right.recognition_scope
        ):
            return False
        if left.polarity != right.polarity and Polarity.UNKNOWN not in (left.polarity, right.polarity):
            return left.object_id_or_value == right.object_id_or_value
        return (
            left.predicate in _LOGICALLY_SINGLE_VALUED_PREDICATES
            and left.polarity == right.polarity == Polarity.AFFIRM
            and left.object_id_or_value != right.object_id_or_value
        )

    def _validated_record_sources(
        self,
        draft: NameRecordDraft,
    ) -> tuple[tuple[MemoryVersion, ...], tuple[Observation, ...]]:
        if not draft.source_memory_version_ids and not draft.source_observation_ids:
            raise self._error(
                MemoryErrorCode.RECORD_SCHEMA_INCOMPLETE,
                "NameRecord requires at least one memory or observation source",
            )
        memories: list[MemoryVersion] = []
        observations: list[Observation] = []
        for memory_id in draft.source_memory_version_ids:
            memories.append(self.get_memory_version(memory_id))
        for observation_id in draft.source_observation_ids:
            observation = self._observations_by_id.get(observation_id)
            if observation is None:
                raise self._error(
                    MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                    "NameRecord references an unknown observation",
                    observation_id=observation_id,
                )
            observations.append(observation)
        source_observation_ids = {
            observation_id
            for memory in memories
            for observation_id in memory.observation_ids
        }
        source_observation_ids.update(item.observation_id for item in observations)
        source_observations = tuple(self._observations_by_id[item] for item in sorted(source_observation_ids))
        return tuple(memories), source_observations

    def _validate_record_structure(self, draft: NameRecordDraft) -> None:
        claim = draft.claim
        if (
            not claim.subject_id
            or not claim.predicate
            or claim.object_id_or_value in (None, UNKNOWN, "")
            or not claim.time_scope
        ):
            raise self._error(
                MemoryErrorCode.RECORD_SCHEMA_INCOMPLETE,
                "formal NameRecord requires all five structured claim elements",
            )
        if draft.recognition_scope != claim.recognition_scope:
            raise self._error(
                MemoryErrorCode.RECORD_SCHEMA_INCOMPLETE,
                "record scope and claim scope must match",
            )
        if draft.recognition_scope != RecognitionScope.HALL_LOCAL:
            raise self._error(
                MemoryErrorCode.RECORD_PERMISSION_EXCEEDED,
                "v0.7 P1-P5 only support HALL_LOCAL recognition",
                recognition_scope=draft.recognition_scope,
            )
        required = _PREDICATE_MIN_PERMISSION.get(claim.predicate)
        if required is None:
            raise self._error(
                MemoryErrorCode.RECORD_PERMISSION_EXCEEDED,
                "predicate has no v0.7 permission rule",
                predicate=claim.predicate,
            )
        if _PERMISSION_RANK[draft.permission_level] < _PERMISSION_RANK[required]:
            raise self._error(
                MemoryErrorCode.RECORD_PERMISSION_EXCEEDED,
                "record permission is below the predicate minimum",
                predicate=claim.predicate,
                supplied=draft.permission_level,
                required=required,
            )
        if draft.permission_level == PermissionLevel.L4_PUBLIC_INSTITUTION:
            raise self._error(
                MemoryErrorCode.RECORD_PERMISSION_EXCEEDED,
                "L4 public institution recognition is out of v0.7 scope",
            )
        if claim.time_scope in {"PAST_ALWAYS", "RETROACTIVE", "BEFORE_D1"}:
            raise self._error(
                MemoryErrorCode.RECORD_ATTEMPTS_PAST_REWRITE,
                "NameRecord cannot retroactively replace occurrence history",
                time_scope=claim.time_scope,
            )

    def _archived_name_record_from_trace(self, name_record_id: str) -> NameRecord | None:
        record: NameRecord | None = None
        for raw_record in self._history_trace:
            kind = raw_record["kind"]
            payload = raw_record["payload"]
            if kind == "NAME_RECORD_CREATED":
                data = payload["name_record"]
                if data["name_record_id"] == name_record_id:
                    record = self._name_record_from_data(data)
            elif kind == "WORLD_ACKNOWLEDGEMENT_COMMITTED":
                acknowledgement_data = payload["acknowledgement"]
                if acknowledgement_data["name_record_id"] == name_record_id and record is not None:
                    record = replace(record, record_status=RecordStatus.ACKNOWLEDGED)
        return record

    def _archived_acknowledgement_from_trace(
        self, acknowledgement_id: str
    ) -> WorldAcknowledgement | None:
        for raw_record in reversed(self._history_trace):
            if raw_record["kind"] != "WORLD_ACKNOWLEDGEMENT_COMMITTED":
                continue
            data = raw_record["payload"]["acknowledgement"]
            if data["acknowledgement_id"] == acknowledgement_id:
                return self._acknowledgement_from_data(data)
        return None

    def _cache_acknowledgement(
        self,
        acknowledgement: WorldAcknowledgement,
        *,
        archive_evicted: bool,
    ) -> WorldAcknowledgement | None:
        evicted = (
            self._acknowledgements[0]
            if self._acknowledgements.maxlen is not None
            and len(self._acknowledgements) >= self._acknowledgements.maxlen
            else None
        )
        self._acknowledgements.append(acknowledgement)
        self._acknowledgements_by_id[acknowledgement.acknowledgement_id] = acknowledgement
        if evicted is not None:
            self._acknowledgements_by_id.pop(evicted.acknowledgement_id, None)
            if archive_evicted:
                self._archive_reference(
                    object_kind="WORLD_ACKNOWLEDGEMENT",
                    object_id=evicted.acknowledgement_id,
                    object_value=evicted,
                    reason="RECENT_ACKNOWLEDGEMENT_CACHE_BOUND",
                )
        return evicted

    def _compact_record_connection_indexes(self) -> None:
        limit = self.config.recent_acknowledgement_cache
        active_ids = set(self._active_connection_version_ids)
        inactive = [
            item for item in self._connection_versions
            if item.connection_version_id not in active_ids
        ]
        while len(inactive) > limit:
            old = inactive.pop(0)
            if old in self._connection_versions:
                self._connection_versions.remove(old)
            self._connection_versions_by_id.pop(old.connection_version_id, None)
            self._archive_reference(
                object_kind="CONNECTION_VERSION",
                object_id=old.connection_version_id,
                object_value=old,
                reason="INACTIVE_CONNECTION_HISTORY_BOUND",
            )

        protected_record_ids = {
            self._connection_versions_by_id[item].based_on_name_record_id
            for item in self._active_connection_version_ids
            if item in self._connection_versions_by_id
        }
        protected_record_ids.update(
            item.name_record_id
            for item in self._name_records
            if item.record_status in (RecordStatus.DRAFT, RecordStatus.CONFIRMED)
        )
        archival_candidates = [
            item for item in self._name_records
            if item.name_record_id not in protected_record_ids
        ]
        while len(archival_candidates) > limit:
            old = archival_candidates.pop(0)
            if old in self._name_records:
                self._name_records.remove(old)
            self._name_records_by_id.pop(old.name_record_id, None)
            self._archive_reference(
                object_kind="NAME_RECORD",
                object_id=old.name_record_id,
                object_value=old,
                reason="ACKNOWLEDGED_NAME_RECORD_HISTORY_BOUND",
            )

        while len(self._conflicts) > limit:
            old = self._conflicts.pop(0)
            self._conflicts_by_id.pop(old.conflict_id, None)
            self._archive_reference(
                object_kind="MEMORY_CONFLICT",
                object_id=old.conflict_id,
                object_value=old,
                reason="RECENT_CONFLICT_HISTORY_BOUND",
            )

    def _acknowledgement_is_same_or_descendant(
        self,
        candidate_acknowledgement_id: str,
        ancestor_acknowledgement_id: str,
    ) -> bool:
        if candidate_acknowledgement_id == ancestor_acknowledgement_id:
            return True
        pending = [candidate_acknowledgement_id]
        visited: set[str] = set()
        while pending:
            acknowledgement_id = pending.pop()
            if acknowledgement_id in visited:
                continue
            visited.add(acknowledgement_id)
            acknowledgement = self._acknowledgements_by_id.get(acknowledgement_id)
            if acknowledgement is None:
                acknowledgement = self._archived_acknowledgement_from_trace(acknowledgement_id)
            if acknowledgement is None:
                continue
            record = self._name_records_by_id.get(acknowledgement.name_record_id)
            if record is None:
                record = self._archived_name_record_from_trace(acknowledgement.name_record_id)
            if record is None:
                continue
            for parent_id in record.parent_acknowledgement_ids:
                if parent_id == ancestor_acknowledgement_id:
                    return True
                pending.append(parent_id)
        return False

    def _validate_record_source_families(
        self,
        draft: NameRecordDraft,
        observations: Sequence[Observation],
    ) -> None:
        families = tuple(draft.source_family_ids)
        if not families or any(not item for item in families):
            raise self._error(
                MemoryErrorCode.RECORD_SCHEMA_INCOMPLETE,
                "NameRecord requires non-empty source families",
            )
        if len(set(families)) != len(families):
            raise self._error(
                MemoryErrorCode.EVIDENCE_SOURCE_FAMILY_DUPLICATE,
                "duplicate copies from one source family do not count as independent support",
                source_family_ids=families,
            )
        observed_families = {item.source_family_id for item in observations}
        if not observed_families.issubset(set(families)):
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "declared source families omit referenced observation provenance",
                missing_source_family_ids=tuple(sorted(observed_families - set(families))),
            )
        parent_ids = set(draft.parent_acknowledgement_ids)
        for observation in observations:
            derived_id = observation.derived_from_acknowledgement_id
            if derived_id is None:
                continue
            if any(
                self._acknowledgement_is_same_or_descendant(derived_id, parent_id)
                for parent_id in parent_ids
            ):
                raise self._error(
                    MemoryErrorCode.EVIDENCE_SELF_PROVING,
                    "manifested evidence cannot prove its parent or ancestor acknowledgement",
                    observation_id=observation.observation_id,
                    acknowledgement_id=derived_id,
                    parent_acknowledgement_ids=tuple(sorted(parent_ids)),
                )

    def _validate_record_consent_and_evidence(
        self,
        draft: NameRecordDraft,
        observations: Sequence[Observation],
    ) -> None:
        claim = draft.claim
        if claim.predicate in _CONSENT_REQUIRED_PREDICATES and claim.subject_id not in draft.consenting_actor_ids:
            raise self._error(
                MemoryErrorCode.RECORD_CONSENT_REQUIRED,
                "this identity, belonging or exclusivity claim requires the current subject's consent",
                subject_id=claim.subject_id,
                predicate=claim.predicate,
            )
        if claim.predicate == "CONTINUES_OLD_RESIDENT_CONNECTION":
            independent_families = {
                item.source_family_id
                for item in observations
                if item.derived_from_acknowledgement_id is None
            }
            body_supported = any(
                item.claim.predicate in {"BODY_CONTINUITY_SUPPORTED", "CURRENT_BODY_MATCHES_OLD_RESIDENT"}
                or bool(item.claim.qualifiers.get("body_continuity_supported", False))
                for item in observations
            )
            if not body_supported or len(independent_families) < 2:
                raise self._error(
                    MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                    "old-resident continuation requires body support and two independent source families",
                    body_supported=body_supported,
                    independent_source_family_count=len(independent_families),
                )

    def create_name_record(self, draft: NameRecordDraft) -> NameRecord:
        self._validate_record_structure(draft)
        _, observations = self._validated_record_sources(draft)
        self._validate_record_source_families(draft, observations)
        self._validate_record_consent_and_evidence(draft, observations)
        record = NameRecord(
            name_record_id=self._next_id("name-record"),
            source_memory_version_ids=draft.source_memory_version_ids,
            source_observation_ids=draft.source_observation_ids,
            source_family_ids=draft.source_family_ids,
            claim=draft.claim,
            permission_level=draft.permission_level,
            record_status=RecordStatus.CONFIRMED if draft.confirmed_by_player else RecordStatus.DRAFT,
            confirmed_by_player=draft.confirmed_by_player,
            consenting_actor_ids=draft.consenting_actor_ids,
            effective_from_tick=draft.effective_from_tick,
            recognition_scope=draft.recognition_scope,
            mitigation_plan_ids=draft.mitigation_plan_ids,
            created_tick=draft.created_tick,
            parent_acknowledgement_ids=draft.parent_acknowledgement_ids,
        )
        self._name_records.append(record)
        self._name_records_by_id[record.name_record_id] = record
        trace_sequence = self._append_trace("NAME_RECORD_CREATED", {"name_record": record})
        self._remember_trace_object("NAME_RECORD", record.name_record_id, trace_sequence)
        return record

    def get_name_record(self, name_record_id: str) -> NameRecord:
        record = self._name_records_by_id.get(name_record_id)
        if record is None:
            record = self._archived_name_record_from_trace(name_record_id)
        if record is None:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "NameRecord does not exist",
                name_record_id=name_record_id,
            )
        return record

    @staticmethod
    def _physical_resource_key(claim: Claim) -> str | None:
        if claim.predicate == "EXCLUSIVE_OCCUPANT_OF":
            return f"physical:{claim.object_id_or_value}"
        return None

    @staticmethod
    def _institutional_resource_key(claim: Claim) -> str | None:
        if claim.predicate == "SOLE_OFFICE_HOLDER_OF":
            return f"institutional:{claim.object_id_or_value}"
        return None

    @staticmethod
    def _capacity_resource_key(claim: Claim) -> str | None:
        if claim.predicate != "CLAIMS_CAPACITY_SLOT_IN":
            return None
        resource = claim.qualifiers.get("resource_key", claim.object_id_or_value)
        return f"capacity:{resource}"

    def _classify_connection_conflict(
        self,
        candidate: Claim,
        existing: Claim,
    ) -> tuple[ConflictType, str] | None:
        if self._claims_logically_exclusive(candidate, existing):
            return (
                ConflictType.LOGICAL_EXCLUSION,
                f"logical:{candidate.subject_id}:{candidate.predicate}:{candidate.time_scope}",
            )
        candidate_key = self._physical_resource_key(candidate)
        existing_key = self._physical_resource_key(existing)
        if candidate_key is not None and candidate_key == existing_key and candidate.subject_id != existing.subject_id:
            return ConflictType.PHYSICAL_EXCLUSIVITY, candidate_key
        candidate_key = self._institutional_resource_key(candidate)
        existing_key = self._institutional_resource_key(existing)
        if candidate_key is not None and candidate_key == existing_key and candidate.subject_id != existing.subject_id:
            return ConflictType.INSTITUTIONAL_EXCLUSIVITY, candidate_key
        candidate_key = self._capacity_resource_key(candidate)
        existing_key = self._capacity_resource_key(existing)
        if candidate_key is not None and candidate_key == existing_key and candidate.subject_id != existing.subject_id:
            declared_capacity = int(candidate.qualifiers.get("declared_capacity", 1))
            existing_capacity = int(existing.qualifiers.get("declared_capacity", declared_capacity))
            if declared_capacity <= 1 or existing_capacity <= 1:
                return ConflictType.DECLARED_CAPACITY_COMPETITION, candidate_key
        return None

    def _prospective_conflicts(
        self,
        record: NameRecord,
        *,
        detected_tick: int,
    ) -> tuple[tuple[MemoryConflict, ConnectionVersion], ...]:
        result: list[tuple[MemoryConflict, ConnectionVersion]] = []
        next_index = self._id_counters.get("conflict", 0) + 1
        capacity_key = self._capacity_resource_key(record.claim)
        capacity_connections: list[ConnectionVersion] = []
        for connection_id in self._active_connection_version_ids:
            existing = self._connection_versions_by_id[connection_id]
            if capacity_key is not None and self._capacity_resource_key(existing.claim) == capacity_key:
                capacity_connections.append(existing)
                continue
            classified = self._classify_connection_conflict(record.claim, existing.claim)
            if classified is None:
                continue
            conflict_type, resource_key = classified
            conflict = MemoryConflict(
                conflict_id=f"conflict.v070.{next_index:08d}",
                conflict_type=conflict_type,
                candidate_ids=(existing.based_on_name_record_id, record.name_record_id),
                resource_key=resource_key,
                detected_tick=detected_tick,
                required_mitigation_types=_CONFLICT_MITIGATIONS[conflict_type],
                resolution_status="PENDING",
            )
            result.append((conflict, existing))
            next_index += 1
        if capacity_key is not None:
            declared_capacity = int(record.claim.qualifiers.get("declared_capacity", 1))
            if declared_capacity < 1:
                raise self._error(
                    MemoryErrorCode.RECORD_SCHEMA_INCOMPLETE,
                    "declared capacity must be a positive integer",
                    declared_capacity=declared_capacity,
                )
            occupied_subjects = {item.claim.subject_id for item in capacity_connections}
            occupied_subjects.add(record.claim.subject_id)
            if len(occupied_subjects) > declared_capacity:
                representative = capacity_connections[0]
                conflict = MemoryConflict(
                    conflict_id=f"conflict.v070.{next_index:08d}",
                    conflict_type=ConflictType.DECLARED_CAPACITY_COMPETITION,
                    candidate_ids=tuple(
                        item.based_on_name_record_id for item in capacity_connections
                    ) + (record.name_record_id,),
                    resource_key=capacity_key,
                    detected_tick=detected_tick,
                    required_mitigation_types=_CONFLICT_MITIGATIONS[
                        ConflictType.DECLARED_CAPACITY_COMPETITION
                    ],
                    resolution_status="PENDING",
                )
                result.append((conflict, representative))
        return tuple(result)

    @staticmethod
    def _mitigation_satisfies(record: NameRecord, conflict: MemoryConflict) -> bool:
        return bool(set(record.mitigation_plan_ids).intersection(conflict.required_mitigation_types))

    @staticmethod
    def _validated_manifestation_changes(
        changes: Mapping[str, Any] | None,
    ) -> tuple[tuple[str, Any], ...]:
        if changes is None:
            return ()
        if not changes:
            raise MemoryKernelError(
                code=MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN,
                message="manifestation transaction cannot be an empty object",
                details=_details(),
            )
        normalized: list[tuple[str, Any]] = []
        for path in sorted(changes):
            if not isinstance(path, str) or not path or "." in path:
                raise MemoryKernelError(
                    code=MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN,
                    message="v0.7 manifestation paths must be non-empty top-level keys",
                    details=_details(path=path),
                )
            normalized.append((path, freeze_value(changes[path])))
        try:
            _canonical_json(dict(normalized))
        except (TypeError, ValueError) as exc:
            raise MemoryKernelError(
                code=MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN,
                message="manifestation values must be canonical JSON-compatible values",
                details=_details(),
            ) from exc
        return tuple(normalized)

    def acknowledge_name_record(
        self,
        name_record_id: str,
        *,
        world_tick: int,
        manifestation_changes: Mapping[str, Any] | None = None,
        manifestation_rule_id: str | None = None,
    ) -> WorldAcknowledgement:
        record = self.get_name_record(name_record_id)
        if record.record_status != RecordStatus.CONFIRMED or not record.confirmed_by_player:
            raise self._error(
                MemoryErrorCode.RECORD_SCHEMA_INCOMPLETE,
                "only a player-confirmed NameRecord can be acknowledged",
                name_record_id=name_record_id,
                record_status=record.record_status,
            )
        normalized_manifestations = self._validated_manifestation_changes(manifestation_changes)
        if normalized_manifestations and not manifestation_rule_id:
            raise self._error(
                MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN,
                "manifestation changes require an explicit deterministic rule id",
                name_record_id=name_record_id,
            )
        if manifestation_rule_id and not normalized_manifestations:
            raise self._error(
                MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN,
                "manifestation rule id cannot be supplied without changes",
                name_record_id=name_record_id,
            )
        conflicts = self._prospective_conflicts(record, detected_tick=world_tick)
        missing = tuple(
            conflict
            for conflict, _ in conflicts
            if not self._mitigation_satisfies(record, conflict)
        )
        if missing:
            first = missing[0]
            raise self._error(
                MemoryErrorCode.CONFLICT_MITIGATION_REQUIRED,
                "typed connection conflict requires an explicit mitigation plan",
                conflict_type=first.conflict_type,
                resource_key=first.resource_key,
                required_mitigation_types=first.required_mitigation_types,
            )

        # All validation is complete above. IDs and mutations below are staged
        # as one deterministic transaction. No callback or user code can observe
        # a connection without its requested manifestation deltas.
        conflict_records = tuple(replace(item, resolution_status="MITIGATED") for item, _ in conflicts)
        superseded_ids: list[str] = []
        superseding_plans = {
            "PLAN_PROSPECTIVE_REPLACEMENT",
            "PLAN_REASSIGN_RESOURCE",
            "PLAN_TRANSFER_OFFICE",
            "PLAN_RELEASE_CAPACITY",
        }
        if conflicts and set(record.mitigation_plan_ids).intersection(superseding_plans):
            superseded_ids.extend(existing.connection_version_id for _, existing in conflicts)
        superseded_ids = list(dict.fromkeys(superseded_ids))
        outcome = (
            AcknowledgementOutcome.PROSPECTIVELY_REPLACED
            if superseded_ids
            else AcknowledgementOutcome.ESTABLISHED
        )
        acknowledgement_id = self._next_id("acknowledgement")
        connection_id = self._next_id("connection-version")
        superseded_connections = tuple(
            self._connection_versions_by_id[item] for item in superseded_ids
        )
        if superseded_connections:
            connection_lineage_id = superseded_connections[0].connection_lineage_id
            version_no = max(item.version_no for item in superseded_connections) + 1
        else:
            connection_lineage_id = self._next_id("connection-lineage")
            version_no = 1
        connection = ConnectionVersion(
            connection_lineage_id=connection_lineage_id,
            connection_version_id=connection_id,
            version_no=version_no,
            claim=record.claim,
            status="ACTIVE",
            based_on_name_record_id=record.name_record_id,
            effective_from_tick=max(world_tick, record.effective_from_tick),
            effective_until_tick=None,
            scope=record.recognition_scope,
            supersedes_connection_version_ids=tuple(superseded_ids),
        )

        staged_manifestation_state = dict(self._manifestation_state)
        manifestation_deltas: list[ManifestationDelta] = []
        derived_family = f"FAMILY_DERIVED_{acknowledgement_id}"
        for path, after in normalized_manifestations:
            before = staged_manifestation_state.get(path, UNKNOWN)
            staged_manifestation_state[path] = after
            manifestation_deltas.append(
                ManifestationDelta(
                    manifestation_delta_id=self._next_id("manifestation-delta"),
                    acknowledgement_id=acknowledgement_id,
                    target_state_path=path,
                    before_value=before,
                    after_value=after,
                    derivation_rule_id=str(manifestation_rule_id),
                    derived_evidence_family_id=derived_family,
                    applied_tick=world_tick,
                )
            )

        acknowledgement = WorldAcknowledgement(
            acknowledgement_id=acknowledgement_id,
            name_record_id=record.name_record_id,
            outcome=outcome,
            created_connection_version_ids=(connection_id,),
            superseded_connection_version_ids=tuple(superseded_ids),
            conflict_ids=tuple(item.conflict_id for item in conflict_records),
            manifestation_delta_ids=tuple(
                item.manifestation_delta_id for item in manifestation_deltas
            ),
            audit_reasons=(
                "STRUCTURE_VALID",
                "PERMISSION_VALID",
                "SOURCE_PROVENANCE_VALID",
                "CONSENT_VALID",
                "CONFLICTS_MITIGATED" if conflicts else "NO_TYPED_CONFLICT",
                "MANIFESTATION_ATOMIC" if manifestation_deltas else "NO_MANIFESTATION_REQUESTED",
            ),
            world_tick=world_tick,
        )

        for superseded_id in superseded_ids:
            old = self._connection_versions_by_id[superseded_id]
            updated = replace(old, status="SUPERSEDED", effective_until_tick=connection.effective_from_tick)
            self._connection_versions_by_id[superseded_id] = updated
            index = self._connection_versions.index(old)
            self._connection_versions[index] = updated
            self._active_connection_version_ids.remove(superseded_id)
        for conflict in conflict_records:
            self._conflicts.append(conflict)
            self._conflicts_by_id[conflict.conflict_id] = conflict
            self._id_counters["conflict"] += 1
        self._connection_versions.append(connection)
        self._connection_versions_by_id[connection.connection_version_id] = connection
        self._active_connection_version_ids.append(connection.connection_version_id)
        updated_record = replace(record, record_status=RecordStatus.ACKNOWLEDGED)
        self._name_records_by_id[record.name_record_id] = updated_record
        record_index = self._name_records.index(record)
        self._name_records[record_index] = updated_record
        self._manifestation_state = staged_manifestation_state
        for delta in manifestation_deltas:
            self._manifestation_audit.append(delta)
        self._cache_acknowledgement(acknowledgement, archive_evicted=False)
        trace_sequence = self._append_trace(
            "WORLD_ACKNOWLEDGEMENT_COMMITTED",
            {
                "acknowledgement": acknowledgement,
                "connection": connection,
                "conflicts": conflict_records,
                "manifestation_deltas": tuple(manifestation_deltas),
                "manifestation_state": self._manifestation_state,
            },
        )
        self._remember_trace_object(
            "WORLD_ACKNOWLEDGEMENT", acknowledgement.acknowledgement_id, trace_sequence
        )
        self._remember_trace_object(
            "CONNECTION_VERSION", connection.connection_version_id, trace_sequence
        )
        for conflict in conflict_records:
            self._remember_trace_object("MEMORY_CONFLICT", conflict.conflict_id, trace_sequence)
        # If the bounded deque evicted an acknowledgement, it is no longer in
        # the lookup cache. Its full value remains in the acknowledgement Trace
        # record and is represented by an archive reference.
        live_ack_ids = {item.acknowledgement_id for item in self._acknowledgements}
        for key in tuple(self._trace_sequences_by_object):
            if key[0] != "WORLD_ACKNOWLEDGEMENT" or key[1] in live_ack_ids:
                continue
            archived = self._archived_acknowledgement_from_trace(key[1])
            if archived is not None:
                self._archive_reference(
                    object_kind="WORLD_ACKNOWLEDGEMENT",
                    object_id=key[1],
                    object_value=archived,
                    reason="RECENT_ACKNOWLEDGEMENT_CACHE_BOUND",
                )
        self._compact_record_connection_indexes()
        return acknowledgement

    def active_connection_claims(self) -> tuple[Claim, ...]:
        return tuple(
            self._connection_versions_by_id[item].claim
            for item in self._active_connection_version_ids
            if self._connection_versions_by_id[item].status == "ACTIVE"
        )

    def _apply_system_projection(
        self,
        *,
        changes: Mapping[str, Any],
        world_tick: int,
        rule_id: str,
    ) -> None:
        if not changes:
            return
        staged = dict(self._manifestation_state)
        for path in sorted(changes):
            if not isinstance(path, str) or not path or "." in path:
                raise self._error(
                    MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN,
                    "system projection contains an invalid top-level state path",
                    path=path,
                )
            staged[path] = freeze_value(changes[path])
        self._manifestation_state = staged
        self._append_trace(
            "SYSTEM_PROJECTION_COMMITTED",
            {
                "world_tick": world_tick,
                "rule_id": rule_id,
                "manifestation_state": self._manifestation_state,
            },
        )

    def manifestation_state(self) -> Mapping[str, Any]:
        return freeze_value(self._manifestation_state)

    def _authoritative_projection(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.config.schema_version,
            "config": self.config,
            "events": tuple(self._events),
            "observations": tuple(self._observations),
            "memory_versions": tuple(
                self._memory_versions[key] for key in sorted(self._memory_versions)
            ),
            "memory_states": tuple(
                self._memory_states[key] for key in sorted(self._memory_states)
            ),
            "forgetting_events": tuple(self._forgetting_events),
            # Pending DRAFT/CONFIRMED records remain in the append-only ledger but
            # are not yet authoritative world state. This preserves P3's atomic
            # rejection invariant.
            "name_records": tuple(
                item
                for item in self._name_records
                if item.record_status
                in (RecordStatus.ACKNOWLEDGED, RecordStatus.WITHDRAWN, RecordStatus.SUPERSEDED)
            ),
            "conflicts": tuple(self._conflicts),
            "connection_versions": tuple(self._connection_versions),
            "active_connection_version_ids": tuple(self._active_connection_version_ids),
            "acknowledgements": tuple(self._acknowledgements),
            "manifestation_state": self._manifestation_state,
            "manifestation_audit": tuple(self._manifestation_audit),
        }

    def _snapshot_projection(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.config.schema_version,
            "config": self.config,
            "config_digest": _sha256(self.config),
            "occurrence_cursor": len(self._events),
            "occurrence_digest": self.occurrence_digest(),
            "events": tuple(self._events),
            "observations": tuple(self._observations),
            "memory_versions": tuple(
                self._memory_versions[key] for key in sorted(self._memory_versions)
            ),
            "memory_states": tuple(
                self._memory_states[key] for key in sorted(self._memory_states)
            ),
            "lineage_versions": {
                key: tuple(self._lineage_versions[key]) for key in sorted(self._lineage_versions)
            },
            "lineage_owner": dict(sorted(self._lineage_owner.items())),
            "actor_lineages": {
                key: tuple(self._actor_lineages[key]) for key in sorted(self._actor_lineages)
            },
            "forgetting_events": tuple(self._forgetting_events),
            "name_records": tuple(self._name_records),
            "conflicts": tuple(self._conflicts),
            "connection_versions": tuple(self._connection_versions),
            "active_connection_version_ids": tuple(self._active_connection_version_ids),
            "recent_acknowledgements": tuple(self._acknowledgements),
            "manifestation_state": self._manifestation_state,
            "manifestation_audit": tuple(self._manifestation_audit),
            "recent_archive_references": tuple(self._recent_archive_references),
            "archive_reference_total": self._archive_reference_total,
            "archived_memory_versions": self._archived_memory_versions,
            "archived_memory_lineages": self._archived_memory_lineages,
            "id_counters": dict(sorted(self._id_counters.items())),
            "history_trace_records": len(self._history_trace),
        }

    def state_digest(self) -> str:
        return _sha256(self._authoritative_projection())

    def save_state(self) -> bytes:
        snapshot = self._snapshot_projection()
        envelope: dict[str, Any] = {
            "format": "WANGSHENG_MEMORY_SNAPSHOT_V0.7",
            "schema_version": self.config.schema_version,
            "snapshot": snapshot,
            "history_trace": tuple(self._history_trace),
            "state_digest": self.state_digest(),
        }
        envelope["snapshot_digest"] = _sha256(envelope)
        return _canonical_json(envelope).encode("utf-8")

    @staticmethod
    def _claim_from_data(data: Mapping[str, Any]) -> Claim:
        return Claim(
            subject_id=str(data["subject_id"]),
            predicate=str(data["predicate"]),
            object_id_or_value=data["object_id_or_value"],
            time_scope=str(data["time_scope"]),
            recognition_scope=RecognitionScope(data["recognition_scope"]),
            polarity=Polarity(data["polarity"]),
            qualifiers=data.get("qualifiers", {}),
        )

    @staticmethod
    def _residue_from_data(data: Mapping[str, Any]) -> EmotionalResidue:
        return EmotionalResidue(
            emotion_type=str(data["emotion_type"]),
            intensity_milli=int(data["intensity_milli"]),
            target_id=str(data["target_id"]),
            origin_memory_version_id=data.get("origin_memory_version_id"),
            decay_per_night_milli=int(data["decay_per_night_milli"]),
            access_independent=bool(data["access_independent"]),
        )

    @classmethod
    def _event_from_data(cls, data: Mapping[str, Any]) -> CanonicalEvent:
        return CanonicalEvent(
            event_id=str(data["event_id"]),
            sequence=int(data["sequence"]),
            world_tick=int(data["world_tick"]),
            event_type=str(data["event_type"]),
            actor_ids=tuple(data["actor_ids"]),
            target_ids=tuple(data["target_ids"]),
            location_id=str(data["location_id"]),
            payload=data["payload"],
            caused_by_action_id=data.get("caused_by_action_id"),
            schema_version=str(data["schema_version"]),
            event_digest=str(data["event_digest"]),
        )

    @classmethod
    def _observation_from_data(cls, data: Mapping[str, Any]) -> Observation:
        return Observation(
            observation_id=str(data["observation_id"]),
            observer_id=str(data["observer_id"]),
            source_kind=SourceKind(data["source_kind"]),
            source_event_ids=tuple(data["source_event_ids"]),
            source_observation_ids=tuple(data["source_observation_ids"]),
            source_actor_id=data.get("source_actor_id"),
            source_evidence_id=data.get("source_evidence_id"),
            source_family_id=str(data["source_family_id"]),
            claim=cls._claim_from_data(data["claim"]),
            confidence_milli=int(data["confidence_milli"]),
            acquired_tick=int(data["acquired_tick"]),
            world_version_seen=int(data["world_version_seen"]),
            derived_from_acknowledgement_id=data.get("derived_from_acknowledgement_id"),
            inference_rule_id=data.get("inference_rule_id"),
        )

    @classmethod
    def _memory_version_from_data(cls, data: Mapping[str, Any]) -> MemoryVersion:
        return MemoryVersion(
            memory_lineage_id=str(data["memory_lineage_id"]),
            memory_version_id=str(data["memory_version_id"]),
            version_no=int(data["version_no"]),
            owner_id=str(data["owner_id"]),
            parent_version_ids=tuple(data["parent_version_ids"]),
            observation_ids=tuple(data["observation_ids"]),
            claim=cls._claim_from_data(data["claim"]),
            source_kind=SourceKind(data["source_kind"]),
            initial_clarity_milli=int(data["initial_clarity_milli"]),
            initial_emotion_residue=tuple(
                cls._residue_from_data(item) for item in data["initial_emotion_residue"]
            ),
            created_tick=int(data["created_tick"]),
            rewrite_reason_code=data.get("rewrite_reason_code"),
        )

    @classmethod
    def _memory_state_from_data(cls, data: Mapping[str, Any]) -> MemoryStateSnapshot:
        return MemoryStateSnapshot(
            memory_version_id=str(data["memory_version_id"]),
            state_revision=int(data["state_revision"]),
            access_state=AccessState(data["access_state"]),
            version_state=VersionState(data["version_state"]),
            clarity_milli=int(data["clarity_milli"]),
            emotion_residue=tuple(cls._residue_from_data(item) for item in data["emotion_residue"]),
            last_transition_event_id=str(data["last_transition_event_id"]),
            last_transition_tick=int(data["last_transition_tick"]),
        )

    @classmethod
    def _forgetting_event_from_data(cls, data: Mapping[str, Any]) -> ForgettingEvent:
        return ForgettingEvent(
            forgetting_event_id=str(data["forgetting_event_id"]),
            target_memory_version_id=str(data["target_memory_version_id"]),
            previous_state_revision=int(data["previous_state_revision"]),
            new_state_revision=int(data["new_state_revision"]),
            mode=ForgettingMode(data["mode"]),
            reason_code=str(data["reason_code"]),
            before_clarity_milli=int(data["before_clarity_milli"]),
            after_clarity_milli=int(data["after_clarity_milli"]),
            before_access_state=AccessState(data["before_access_state"]),
            after_access_state=AccessState(data["after_access_state"]),
            emotion_deltas=tuple(cls._residue_from_data(item) for item in data["emotion_deltas"]),
            world_tick=int(data["world_tick"]),
        )

    @classmethod
    def _name_record_from_data(cls, data: Mapping[str, Any]) -> NameRecord:
        return NameRecord(
            name_record_id=str(data["name_record_id"]),
            source_memory_version_ids=tuple(data["source_memory_version_ids"]),
            source_observation_ids=tuple(data["source_observation_ids"]),
            source_family_ids=tuple(data["source_family_ids"]),
            claim=cls._claim_from_data(data["claim"]),
            permission_level=PermissionLevel(data["permission_level"]),
            record_status=RecordStatus(data["record_status"]),
            confirmed_by_player=bool(data["confirmed_by_player"]),
            consenting_actor_ids=tuple(data["consenting_actor_ids"]),
            effective_from_tick=int(data["effective_from_tick"]),
            recognition_scope=RecognitionScope(data["recognition_scope"]),
            mitigation_plan_ids=tuple(data["mitigation_plan_ids"]),
            created_tick=int(data["created_tick"]),
            parent_acknowledgement_ids=tuple(data.get("parent_acknowledgement_ids", ())),
        )

    @staticmethod
    def _conflict_from_data(data: Mapping[str, Any]) -> MemoryConflict:
        return MemoryConflict(
            conflict_id=str(data["conflict_id"]),
            conflict_type=ConflictType(data["conflict_type"]),
            candidate_ids=tuple(data["candidate_ids"]),
            resource_key=str(data["resource_key"]),
            detected_tick=int(data["detected_tick"]),
            required_mitigation_types=tuple(data["required_mitigation_types"]),
            resolution_status=str(data["resolution_status"]),
        )

    @classmethod
    def _connection_from_data(cls, data: Mapping[str, Any]) -> ConnectionVersion:
        return ConnectionVersion(
            connection_lineage_id=str(data["connection_lineage_id"]),
            connection_version_id=str(data["connection_version_id"]),
            version_no=int(data["version_no"]),
            claim=cls._claim_from_data(data["claim"]),
            status=str(data["status"]),
            based_on_name_record_id=str(data["based_on_name_record_id"]),
            effective_from_tick=int(data["effective_from_tick"]),
            effective_until_tick=(
                int(data["effective_until_tick"])
                if data.get("effective_until_tick") is not None
                else None
            ),
            scope=RecognitionScope(data["scope"]),
            supersedes_connection_version_ids=tuple(data["supersedes_connection_version_ids"]),
        )

    @staticmethod
    def _manifestation_delta_from_data(data: Mapping[str, Any]) -> ManifestationDelta:
        return ManifestationDelta(
            manifestation_delta_id=str(data["manifestation_delta_id"]),
            acknowledgement_id=str(data["acknowledgement_id"]),
            target_state_path=str(data["target_state_path"]),
            before_value=data["before_value"],
            after_value=data["after_value"],
            derivation_rule_id=str(data["derivation_rule_id"]),
            derived_evidence_family_id=str(data["derived_evidence_family_id"]),
            applied_tick=int(data["applied_tick"]),
        )

    @staticmethod
    def _acknowledgement_from_data(data: Mapping[str, Any]) -> WorldAcknowledgement:
        return WorldAcknowledgement(
            acknowledgement_id=str(data["acknowledgement_id"]),
            name_record_id=str(data["name_record_id"]),
            outcome=AcknowledgementOutcome(data["outcome"]),
            created_connection_version_ids=tuple(data["created_connection_version_ids"]),
            superseded_connection_version_ids=tuple(data["superseded_connection_version_ids"]),
            conflict_ids=tuple(data["conflict_ids"]),
            manifestation_delta_ids=tuple(data["manifestation_delta_ids"]),
            audit_reasons=tuple(data["audit_reasons"]),
            world_tick=int(data["world_tick"]),
        )

    @staticmethod
    def _config_from_data(data: Mapping[str, Any]) -> KernelConfig:
        return KernelConfig(
            active_memory_lineages_per_actor=int(data["active_memory_lineages_per_actor"]),
            active_memory_versions_per_lineage=int(data["active_memory_versions_per_lineage"]),
            recent_forgetting_events_cache=int(data["recent_forgetting_events_cache"]),
            recent_acknowledgement_cache=int(data["recent_acknowledgement_cache"]),
            belief_query_cache_per_actor=int(data["belief_query_cache_per_actor"]),
            manifestation_audit_window=int(data["manifestation_audit_window"]),
            schema_version=str(data["schema_version"]),
        )

    @staticmethod
    def _derive_id_counters(value: Any) -> dict[str, int]:
        counters: dict[str, int] = defaultdict(int)

        def visit(item: Any) -> None:
            if isinstance(item, Mapping):
                for key, child in item.items():
                    visit(key)
                    visit(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)
            elif isinstance(item, str):
                for match in re.finditer(r"([a-z][a-z0-9-]*)\.v070\.(\d{8})", item):
                    counters[match.group(1)] = max(counters[match.group(1)], int(match.group(2)))

        visit(value)
        return dict(counters)

    @classmethod
    def _from_history_trace(
        cls,
        history_trace: Sequence[Mapping[str, Any]],
        *,
        config: KernelConfig,
    ) -> "MemoryVersioningKernel":
        kernel = cls(config=config)
        frozen_trace: list[Mapping[str, Any]] = []
        for expected_sequence, raw_record in enumerate(history_trace, start=1):
            if int(raw_record.get("sequence", -1)) != expected_sequence:
                raise kernel._error(
                    MemoryErrorCode.REPLAY_DIGEST_MISMATCH,
                    "history trace sequence is not contiguous",
                    expected_sequence=expected_sequence,
                    actual_sequence=raw_record.get("sequence"),
                )
            kind = str(raw_record.get("kind", ""))
            payload = raw_record.get("payload", {})
            if not isinstance(payload, Mapping):
                raise kernel._error(
                    MemoryErrorCode.REPLAY_DIGEST_MISMATCH,
                    "history trace payload is not an object",
                    sequence=expected_sequence,
                )
            if kind == "CANONICAL_EVENT_COMMITTED":
                event = cls._event_from_data(payload["event"])
                kernel._events.append(event)
                kernel._events_by_id[event.event_id] = event
            elif kind == "OBSERVATION_RECORDED":
                observation = cls._observation_from_data(payload["observation"])
                kernel._observations.append(observation)
                kernel._observations_by_id[observation.observation_id] = observation
            elif kind == "MEMORY_VERSION_CREATED":
                version = cls._memory_version_from_data(payload["memory_version"])
                state = cls._memory_state_from_data(payload["state"])
                is_new_lineage = version.memory_lineage_id not in kernel._lineage_owner
                kernel._memory_versions[version.memory_version_id] = version
                kernel._memory_states[state.memory_version_id] = state
                kernel._lineage_versions[version.memory_lineage_id].append(version.memory_version_id)
                if is_new_lineage:
                    kernel._lineage_owner[version.memory_lineage_id] = version.owner_id
                    kernel._actor_lineages[version.owner_id].append(version.memory_lineage_id)
                    kernel._remember_trace_object(
                        "MEMORY_LINEAGE", version.memory_lineage_id, expected_sequence
                    )
                kernel._remember_trace_object(
                    "MEMORY_VERSION", version.memory_version_id, expected_sequence
                )
            elif kind == "MEMORY_VERSION_REWRITTEN":
                parent_id = str(payload["parent_memory_version_id"])
                new_id = str(payload["new_memory_version_id"])
                old = kernel._memory_states[parent_id]
                created_tick = kernel._memory_versions[new_id].created_tick
                kernel._memory_states[parent_id] = replace(
                    old,
                    state_revision=old.state_revision + 1,
                    version_state=VersionState.REWRITTEN,
                    last_transition_event_id=f"memory-rewritten-by:{new_id}",
                    last_transition_tick=created_tick,
                )
            elif kind == "FORGETTING_EVENT_APPLIED":
                forgetting = cls._forgetting_event_from_data(payload["forgetting_event"])
                state = cls._memory_state_from_data(payload["new_state"])
                kernel._memory_states[state.memory_version_id] = state
                kernel._forgetting_events.append(forgetting)
            elif kind == "MEMORY_CONTRADICTION_REGISTERED":
                ids = tuple(payload["memory_version_ids"])
                detected_tick = int(payload["detected_tick"])
                for index, memory_id in enumerate(ids):
                    old = kernel._memory_states[memory_id]
                    kernel._memory_states[memory_id] = replace(
                        old,
                        state_revision=old.state_revision + 1,
                        version_state=VersionState.CONTRADICTED,
                        last_transition_event_id=f"memory-contradiction:{detected_tick}:{index + 1}",
                        last_transition_tick=detected_tick,
                    )
            elif kind == "NAME_RECORD_CREATED":
                record = cls._name_record_from_data(payload["name_record"])
                kernel._name_records.append(record)
                kernel._name_records_by_id[record.name_record_id] = record
                kernel._remember_trace_object("NAME_RECORD", record.name_record_id, expected_sequence)
            elif kind == "WORLD_ACKNOWLEDGEMENT_COMMITTED":
                acknowledgement = cls._acknowledgement_from_data(payload["acknowledgement"])
                connection = cls._connection_from_data(payload["connection"])
                conflicts = tuple(cls._conflict_from_data(item) for item in payload.get("conflicts", ()))
                for superseded_id in acknowledgement.superseded_connection_version_ids:
                    old = kernel._connection_versions_by_id[superseded_id]
                    updated = replace(
                        old,
                        status="SUPERSEDED",
                        effective_until_tick=connection.effective_from_tick,
                    )
                    kernel._connection_versions_by_id[superseded_id] = updated
                    kernel._connection_versions[kernel._connection_versions.index(old)] = updated
                    if superseded_id in kernel._active_connection_version_ids:
                        kernel._active_connection_version_ids.remove(superseded_id)
                for conflict in conflicts:
                    kernel._conflicts.append(conflict)
                    kernel._conflicts_by_id[conflict.conflict_id] = conflict
                kernel._connection_versions.append(connection)
                kernel._connection_versions_by_id[connection.connection_version_id] = connection
                kernel._active_connection_version_ids.append(connection.connection_version_id)
                record = kernel._name_records_by_id[acknowledgement.name_record_id]
                updated_record = replace(record, record_status=RecordStatus.ACKNOWLEDGED)
                kernel._name_records_by_id[record.name_record_id] = updated_record
                kernel._name_records[kernel._name_records.index(record)] = updated_record
                manifestation_deltas = tuple(
                    cls._manifestation_delta_from_data(item)
                    for item in payload.get("manifestation_deltas", ())
                )
                for delta in manifestation_deltas:
                    kernel._manifestation_audit.append(delta)
                if "manifestation_state" in payload:
                    kernel._manifestation_state = dict(payload["manifestation_state"])
                kernel._cache_acknowledgement(acknowledgement, archive_evicted=False)
                kernel._remember_trace_object(
                    "WORLD_ACKNOWLEDGEMENT", acknowledgement.acknowledgement_id, expected_sequence
                )
                kernel._remember_trace_object(
                    "CONNECTION_VERSION", connection.connection_version_id, expected_sequence
                )
                for conflict in conflicts:
                    kernel._remember_trace_object("MEMORY_CONFLICT", conflict.conflict_id, expected_sequence)
            elif kind == "LIVE_INDEX_EVICTED":
                reference = cls._archive_reference_from_data(payload["archive_reference"])
                kernel._recent_archive_references.append(reference)
                kernel._archive_reference_total += 1
                if reference.object_kind == "MEMORY_VERSION":
                    version = kernel._memory_versions.pop(reference.object_id, None)
                    kernel._memory_states.pop(reference.object_id, None)
                    if version is not None:
                        lineage_ids = kernel._lineage_versions.get(version.memory_lineage_id)
                        if lineage_ids is not None and reference.object_id in lineage_ids:
                            lineage_ids.remove(reference.object_id)
                    kernel._archived_memory_versions += 1
                elif reference.object_kind == "MEMORY_LINEAGE":
                    owner_id = kernel._lineage_owner.pop(reference.object_id, None)
                    kernel._lineage_versions.pop(reference.object_id, None)
                    if owner_id is not None:
                        actor_lineages = kernel._actor_lineages.get(owner_id)
                        if actor_lineages is not None and reference.object_id in actor_lineages:
                            actor_lineages.remove(reference.object_id)
                        if actor_lineages is not None and not actor_lineages:
                            kernel._actor_lineages.pop(owner_id, None)
                    kernel._archived_memory_lineages += 1
                elif reference.object_kind == "WORLD_ACKNOWLEDGEMENT":
                    kernel._acknowledgements_by_id.pop(reference.object_id, None)
                elif reference.object_kind == "CONNECTION_VERSION":
                    item = kernel._connection_versions_by_id.pop(reference.object_id, None)
                    if item is not None and item in kernel._connection_versions:
                        kernel._connection_versions.remove(item)
                elif reference.object_kind == "NAME_RECORD":
                    item = kernel._name_records_by_id.pop(reference.object_id, None)
                    if item is not None and item in kernel._name_records:
                        kernel._name_records.remove(item)
                elif reference.object_kind == "MEMORY_CONFLICT":
                    item = kernel._conflicts_by_id.pop(reference.object_id, None)
                    if item is not None and item in kernel._conflicts:
                        kernel._conflicts.remove(item)
                kernel._trace_sequences_by_object.pop(
                    (reference.object_kind, reference.object_id), None
                )
            elif kind == "SYSTEM_PROJECTION_COMMITTED":
                kernel._manifestation_state = dict(payload["manifestation_state"])
            else:
                raise kernel._error(
                    MemoryErrorCode.REPLAY_DIGEST_MISMATCH,
                    "history trace contains an unsupported record kind",
                    kind=kind,
                    sequence=expected_sequence,
                )
            frozen_trace.append(freeze_value(raw_record))

        kernel._history_trace = frozen_trace
        kernel._id_counters = defaultdict(int, cls._derive_id_counters(history_trace))
        return kernel

    @classmethod
    def load_state(cls, payload: bytes) -> "MemoryVersioningKernel":
        try:
            envelope = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MemoryKernelError(
                code=MemoryErrorCode.SAVE_DIGEST_MISMATCH,
                message="snapshot is not canonical UTF-8 JSON",
                details=_details(),
            ) from exc
        if not isinstance(envelope, dict) or envelope.get("format") != "WANGSHENG_MEMORY_SNAPSHOT_V0.7":
            raise MemoryKernelError(
                code=MemoryErrorCode.SAVE_DIGEST_MISMATCH,
                message="snapshot format identifier is invalid",
                details=_details(format=envelope.get("format") if isinstance(envelope, dict) else None),
            )
        supplied_digest = envelope.get("snapshot_digest")
        digest_input = dict(envelope)
        digest_input.pop("snapshot_digest", None)
        if supplied_digest != _sha256(digest_input):
            raise MemoryKernelError(
                code=MemoryErrorCode.SAVE_DIGEST_MISMATCH,
                message="snapshot envelope digest does not match its contents",
                details=_details(),
            )
        snapshot = envelope.get("snapshot")
        history_trace = envelope.get("history_trace")
        if not isinstance(snapshot, Mapping) or not isinstance(history_trace, list):
            raise MemoryKernelError(
                code=MemoryErrorCode.SAVE_DIGEST_MISMATCH,
                message="snapshot is missing projection or history trace",
                details=_details(),
            )
        config = cls._config_from_data(snapshot["config"])
        if snapshot.get("config_digest") != _sha256(config):
            raise MemoryKernelError(
                code=MemoryErrorCode.SAVE_DIGEST_MISMATCH,
                message="snapshot config digest is invalid",
                details=_details(),
            )
        replayed = cls._from_history_trace(history_trace, config=config)
        if primitive_value(replayed._snapshot_projection()) != primitive_value(snapshot):
            raise replayed._error(
                MemoryErrorCode.SAVE_DIGEST_MISMATCH,
                "snapshot projection does not match deterministic trace replay",
            )
        if replayed.state_digest() != envelope.get("state_digest"):
            raise replayed._error(
                MemoryErrorCode.SAVE_DIGEST_MISMATCH,
                "snapshot authoritative state digest does not match replay",
            )
        return replayed

    def replay_digest(self) -> str:
        replayed = self._from_history_trace(self._history_trace, config=self.config)
        digest = replayed.state_digest()
        if digest != self.state_digest():
            raise self._error(
                MemoryErrorCode.REPLAY_DIGEST_MISMATCH,
                "history trace replay does not reconstruct current authoritative state",
                snapshot_digest=self.state_digest(),
                replay_digest=digest,
            )
        return digest

    @staticmethod
    def _load_xiaoman_fixture(fixture_path: Path) -> Mapping[str, Any]:
        data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        if data.get("fixture_id") != "V070_XIAOMAN_THREE_DAY_KERNEL" or data.get("schema_version") != "0.7":
            raise ValueError("fixture is not the frozen v0.7 Xiaoman kernel fixture")
        return data

    @classmethod
    def _claim_from_fixture(cls, data: Mapping[str, Any]) -> Claim:
        return Claim(
            subject_id=str(data["subject_id"]),
            predicate=str(data["predicate"]),
            object_id_or_value=data["object_id_or_value"],
            time_scope=str(data["time_scope"]),
            recognition_scope=RecognitionScope(data["recognition_scope"]),
            polarity=Polarity(data.get("polarity", "AFFIRM")),
            qualifiers=data.get("qualifiers", {}),
        )

    @classmethod
    def _build_xiaoman_day1_base(
        cls,
        fixture: Mapping[str, Any],
    ) -> tuple["MemoryVersioningKernel", Mapping[str, tuple[Observation, MemoryVersion]]]:
        kernel = cls()
        committed: dict[str, CanonicalEvent] = {}
        for world_tick, event_data in enumerate(fixture["day1_events"], start=1):
            committed[event_data["id"]] = kernel.commit_event(
                world_tick=world_tick,
                event_type=event_data["type"],
                actor_ids=(event_data["actor"],),
                target_ids=(event_data["target"],),
                location_id="location.front_hall",
                payload={"fixture_event_id": event_data["id"], **event_data["payload"]},
            )

        candidates = {item["id"]: item for item in fixture["night1_candidates"]}
        source_specs = {
            "CAND_D1_NAME_SELF_REPORT": (
                "EV_D1_SELF_NAME",
                SourceKind.HEARD,
                "actor.xiaoman",
                "FAMILY_XIAOMAN_SELF_REPORT",
                None,
            ),
            "CAND_D1_CRANE_CONNECTION": (
                "EV_D1_CRANE_TRANSFER",
                SourceKind.INFERRED,
                None,
                "FAMILY_PAPER_CRANE_OLD_NETWORK",
                "RULE_CRANE_TRANSFER_IMPLIES_AUDITABLE_OLD_CONNECTION",
            ),
            "CAND_D1_QINGYAN_UNKNOWN": (
                "EV_D1_QINGYAN_UNKNOWN",
                SourceKind.HEARD,
                "actor.qingyan",
                "FAMILY_QINGYAN_SELF_REPORT",
                None,
            ),
        }
        sources: dict[str, tuple[Observation, MemoryVersion]] = {}
        for candidate_id, (event_key, source_kind, source_actor, family, inference_rule) in source_specs.items():
            candidate_claim = cls._claim_from_fixture(candidates[candidate_id]["claim"])
            event = committed[event_key]
            observation = kernel.record_observation(
                ObservationDraft(
                    observer_id="actor.player",
                    source_kind=source_kind,
                    source_event_ids=(event.event_id,),
                    source_observation_ids=(),
                    source_actor_id=source_actor,
                    source_evidence_id=None,
                    source_family_id=family,
                    claim=candidate_claim,
                    confidence_milli=900,
                    acquired_tick=event.world_tick,
                    world_version_seen=event.sequence,
                    inference_rule_id=inference_rule,
                ),
                visibility_claim=candidate_claim,
            )
            memory = kernel.create_memory(
                owner_id="actor.player",
                observation_ids=(observation.observation_id,),
                claim=candidate_claim,
                source_kind=source_kind,
                initial_clarity_milli=850,
                initial_emotion_residue=(),
                created_tick=event.world_tick,
            )
            sources[candidate_id] = (observation, memory)
        return kernel, MappingProxyType(sources)

    @classmethod
    def _create_fixture_record(
        cls,
        kernel: "MemoryVersioningKernel",
        *,
        claim: Claim,
        permission: PermissionLevel,
        observations: Sequence[Observation],
        memories: Sequence[MemoryVersion],
        consenting_actor_ids: Sequence[str] = (),
        effective_from_tick: int,
        created_tick: int,
        manifestation_changes: Mapping[str, Any] | None = None,
        manifestation_rule_id: str | None = None,
    ) -> WorldAcknowledgement:
        record = kernel.create_name_record(
            NameRecordDraft(
                source_memory_version_ids=tuple(item.memory_version_id for item in memories),
                source_observation_ids=tuple(item.observation_id for item in observations),
                source_family_ids=tuple(dict.fromkeys(item.source_family_id for item in observations)),
                claim=claim,
                permission_level=permission,
                confirmed_by_player=True,
                consenting_actor_ids=tuple(consenting_actor_ids),
                effective_from_tick=effective_from_tick,
                recognition_scope=RecognitionScope.HALL_LOCAL,
                mitigation_plan_ids=(),
                created_tick=created_tick,
            )
        )
        return kernel.acknowledge_name_record(
            record.name_record_id,
            world_tick=created_tick,
            manifestation_changes=manifestation_changes,
            manifestation_rule_id=manifestation_rule_id,
        )

    @classmethod
    def _build_xiaoman_day1_branch(
        cls,
        fixture: Mapping[str, Any],
        candidate_id: str,
    ) -> tuple["MemoryVersioningKernel", BranchResult]:
        kernel, sources = cls._build_xiaoman_day1_base(fixture)
        candidate = next(item for item in fixture["night1_candidates"] if item["id"] == candidate_id)
        delta = fixture["day2_expected_deltas"][candidate_id]
        if candidate_id == "CAND_D1_NONE":
            for _, memory in sources.values():
                kernel.transition_memory(
                    memory.memory_version_id,
                    mode=ForgettingMode.FACT_ONLY,
                    reason_code="D1_UNRECORDED_NIGHT_DECAY",
                    decay_per_night_milli=300,
                    explicit_penalty_milli=0,
                    explicit_rehearsal_bonus_milli=0,
                    world_tick=20,
                )
            kernel._apply_system_projection(
                changes=delta,
                world_tick=20,
                rule_id="RULE_D1_NO_RECORD_DECAY",
            )
        else:
            observation, memory = sources[candidate_id]
            cls._create_fixture_record(
                kernel,
                claim=cls._claim_from_fixture(candidate["claim"]),
                permission=PermissionLevel(candidate["permission"]),
                observations=(observation,),
                memories=(memory,),
                effective_from_tick=10,
                created_tick=20,
                manifestation_changes=delta,
                manifestation_rule_id=f"RULE_D1_BRANCH_{candidate_id}",
            )
        result = BranchResult(
            branch_id=candidate_id,
            occurrence_digest=kernel.occurrence_digest(),
            state_digest=kernel.state_digest(),
            manifestation_state=kernel.manifestation_state(),
            active_connection_claims=kernel.active_connection_claims(),
        )
        return kernel, result

    @classmethod
    def run_xiaoman_day1_branches(cls, fixture_path: Path) -> Mapping[str, BranchResult]:
        fixture = cls._load_xiaoman_fixture(fixture_path)
        return MappingProxyType(
            {
                item["id"]: cls._build_xiaoman_day1_branch(fixture, item["id"])[1]
                for item in fixture["night1_candidates"]
            }
        )

    @classmethod
    def _build_xiaoman_day3_base(
        cls,
        fixture: Mapping[str, Any],
    ) -> tuple[
        "MemoryVersioningKernel",
        Mapping[str, tuple[Observation, MemoryVersion]],
        tuple[Observation, MemoryVersion],
    ]:
        kernel, sources = cls._build_xiaoman_day1_base(fixture)
        archive_event = kernel.commit_event(
            world_tick=5,
            event_type="ARCHIVE_DEATH_RECORD_READ",
            actor_ids=("actor.player",),
            target_ids=("actor.xiaoman",),
            location_id="location.front_hall",
            payload={"historical_event": "ten_year_old_death_event", "preserved": True},
        )
        body_event = kernel.commit_event(
            world_tick=6,
            event_type="BODY_CONTINUITY_INSPECTED",
            actor_ids=("actor.player",),
            target_ids=("actor.xiaoman",),
            location_id="location.front_hall",
            payload={"body_continuity_supported": True},
        )
        body_claim = Claim(
            subject_id="actor.xiaoman",
            predicate="BODY_CONTINUITY_SUPPORTED",
            object_id_or_value=True,
            time_scope="D3_CURRENT",
            recognition_scope=RecognitionScope.HALL_LOCAL,
            qualifiers={"body_continuity_supported": True, "archive_event_id": archive_event.event_id},
        )
        body_observation = kernel.record_observation(
            ObservationDraft(
                observer_id="actor.player",
                source_kind=SourceKind.EXPERIENCED,
                source_event_ids=(body_event.event_id,),
                source_observation_ids=(),
                source_actor_id=None,
                source_evidence_id=archive_event.event_id,
                source_family_id="FAMILY_BODY_CONTINUITY_INSPECTION",
                claim=body_claim,
                confidence_milli=850,
                acquired_tick=6,
                world_version_seen=body_event.sequence,
            ),
            visibility_claim=body_claim,
        )
        body_memory = kernel.create_memory(
            owner_id="actor.player",
            observation_ids=(body_observation.observation_id,),
            claim=body_claim,
            source_kind=SourceKind.EXPERIENCED,
            initial_clarity_milli=850,
            initial_emotion_residue=(),
            created_tick=6,
        )
        return kernel, sources, (body_observation, body_memory)

    @classmethod
    def _outcome_claim(cls, outcome_id: str, outcome: Mapping[str, Any]) -> Claim:
        predicate = str(outcome["connection"])
        object_value: Any
        if predicate in {"CURRENT_PERSON_USES_NAME_XIAOMAN", "NAME_RECOGNIZED_HISTORY_UNRESOLVED"}:
            object_value = "小满"
        else:
            object_value = "institution.wangsheng_hall"
        return Claim(
            subject_id="actor.xiaoman",
            predicate=predicate,
            object_id_or_value=object_value,
            time_scope="FROM_D3_FORWARD",
            recognition_scope=RecognitionScope.HALL_LOCAL,
            qualifiers={"fixture_outcome_id": outcome_id, "does_not_rewrite_occurrence": True},
        )

    @classmethod
    def _build_xiaoman_day3_branch(
        cls,
        fixture: Mapping[str, Any],
        outcome_id: str,
    ) -> tuple["MemoryVersioningKernel", BranchResult]:
        kernel, sources, body_source = cls._build_xiaoman_day3_base(fixture)
        outcome = fixture["day3_outcomes"][outcome_id]
        manifestations = tuple(outcome["manifestations"])
        changes: dict[str, Any] = {
            "outcome_id": outcome_id,
            "manifestations": manifestations,
            "inherited": tuple(),
        }
        if outcome_id == "REFUSED":
            kernel._apply_system_projection(
                changes=changes,
                world_tick=30,
                rule_id="RULE_D3_PLAYER_REFUSED_RECORD",
            )
        else:
            self_observation, self_memory = sources["CAND_D1_NAME_SELF_REPORT"]
            observations: tuple[Observation, ...] = (self_observation,)
            memories: tuple[MemoryVersion, ...] = (self_memory,)
            if outcome_id == "OLD_RESIDENT_CONTINUATION":
                observations = (self_observation, body_source[0])
                memories = (self_memory, body_source[1])
            cls._create_fixture_record(
                kernel,
                claim=cls._outcome_claim(outcome_id, outcome),
                permission=PermissionLevel(outcome["permission"]),
                observations=observations,
                memories=memories,
                consenting_actor_ids=("actor.xiaoman",),
                effective_from_tick=30,
                created_tick=30,
                manifestation_changes=changes,
                manifestation_rule_id=f"RULE_D3_OUTCOME_{outcome_id}",
            )
        result = BranchResult(
            branch_id=outcome_id,
            occurrence_digest=kernel.occurrence_digest(),
            state_digest=kernel.state_digest(),
            manifestation_state=kernel.manifestation_state(),
            active_connection_claims=kernel.active_connection_claims(),
        )
        return kernel, result

    @classmethod
    def run_xiaoman_day3_outcomes(cls, fixture_path: Path) -> Mapping[str, BranchResult]:
        fixture = cls._load_xiaoman_fixture(fixture_path)
        return MappingProxyType(
            {
                outcome_id: cls._build_xiaoman_day3_branch(fixture, outcome_id)[1]
                for outcome_id in fixture["day3_outcomes"]
            }
        )

    @classmethod
    def verify_xiaoman_save_load_replay(cls, fixture_path: Path) -> ReplayVerification:
        fixture = cls._load_xiaoman_fixture(fixture_path)
        checkpoints: list[MemoryVersioningKernel] = []
        base, _ = cls._build_xiaoman_day1_base(fixture)
        checkpoints.append(base)
        day1_kernel, _ = cls._build_xiaoman_day1_branch(fixture, "CAND_D1_NAME_SELF_REPORT")
        checkpoints.append(day1_kernel)
        final_kernel, _ = cls._build_xiaoman_day3_branch(fixture, "OLD_RESIDENT_CONTINUATION")
        checkpoints.append(final_kernel)

        matches = True
        for kernel in checkpoints:
            payload = kernel.save_state()
            loaded = cls.load_state(payload)
            matches = matches and loaded.state_digest() == kernel.state_digest()
            matches = matches and loaded.replay_digest() == kernel.state_digest()
            matches = matches and loaded.save_state() == payload

        day1 = cls.run_xiaoman_day1_branches(fixture_path)
        day3 = cls.run_xiaoman_day3_outcomes(fixture_path)
        branch_digests = {
            **{f"D1:{key}": value.state_digest for key, value in day1.items()},
            **{f"D3:{key}": value.state_digest for key, value in day3.items()},
        }
        snapshot_digest = final_kernel.state_digest()
        replay_digest = final_kernel.replay_digest()
        return ReplayVerification(
            checkpoints=len(checkpoints),
            snapshot_digest=snapshot_digest,
            replay_digest=replay_digest,
            state_match=matches and snapshot_digest == replay_digest,
            branch_digests=branch_digests,
        )

    def run_same_world_stress(self, *, transitions: int, seed: int) -> StressSummary:
        if transitions <= 0:
            raise ValueError("transitions must be positive")
        rng = random.Random(seed)
        owner_id = "actor.stress_witness"
        aliases = ("STRESS_ALIAS_A", "STRESS_ALIAS_B")
        observations: dict[str, Observation] = {}
        claims: dict[str, Claim] = {}
        for index, alias in enumerate(aliases, start=1):
            claim = Claim(
                subject_id="actor.stress_subject",
                predicate="SELF_IDENTIFIED_AS",
                object_id_or_value=alias,
                time_scope="STRESS_FORWARD",
                recognition_scope=RecognitionScope.HALL_LOCAL,
                polarity=Polarity.AFFIRM,
                qualifiers={"stress_alias_index": index},
            )
            event = self.commit_event(
                world_tick=0,
                event_type="STRESS_ALIAS_OBSERVED",
                actor_ids=("actor.stress_subject",),
                target_ids=(owner_id,),
                location_id="location.stress_hall",
                payload={"alias": alias, "seed": seed},
            )
            observation = self.record_observation(
                ObservationDraft(
                    observer_id=owner_id,
                    source_kind=SourceKind.EXPERIENCED,
                    source_event_ids=(event.event_id,),
                    source_observation_ids=(),
                    source_actor_id=None,
                    source_evidence_id=event.event_id,
                    source_family_id=f"FAMILY_STRESS_{alias}",
                    claim=claim,
                    confidence_milli=1000,
                    acquired_tick=0,
                    world_version_seen=event.sequence,
                ),
                visibility_claim=claim,
            )
            claims[alias] = claim
            observations[alias] = observation

        latest_by_alias: dict[str, str] = {}
        all_memory_ids: list[str] = []
        for alias in aliases:
            version = self.create_memory(
                owner_id=owner_id,
                observation_ids=(observations[alias].observation_id,),
                claim=claims[alias],
                source_kind=SourceKind.EXPERIENCED,
                initial_clarity_milli=900,
                initial_emotion_residue=(),
                created_tick=0,
            )
            latest_by_alias[alias] = version.memory_version_id
            all_memory_ids.append(version.memory_version_id)

        pending_record_id: str | None = None
        pending_alias: str | None = None
        memory_step = 0
        acknowledgement_count = 0
        max_active_lineages = 0
        max_versions_per_lineage = 0
        max_forgetting = 0
        max_acknowledgements = 0
        max_query_cache = 0
        max_manifestation_audit = 0
        max_live_name_records = 0
        max_live_connections = 0
        max_archive_refs = 0
        lineage_cycles = 0
        partial_commits = 0
        digest_mismatches = 0

        def update_maxima() -> None:
            nonlocal max_active_lineages, max_versions_per_lineage
            nonlocal max_forgetting, max_acknowledgements, max_query_cache
            nonlocal max_manifestation_audit, max_live_name_records
            nonlocal max_live_connections, max_archive_refs
            max_active_lineages = max(
                max_active_lineages,
                max((len(items) for items in self._actor_lineages.values()), default=0),
            )
            max_versions_per_lineage = max(
                max_versions_per_lineage,
                max((len(items) for items in self._lineage_versions.values()), default=0),
            )
            max_forgetting = max(max_forgetting, len(self._forgetting_events))
            max_acknowledgements = max(max_acknowledgements, len(self._acknowledgements))
            max_query_cache = max(
                max_query_cache,
                max((len(items) for items in self._belief_query_cache.values()), default=0),
            )
            max_manifestation_audit = max(
                max_manifestation_audit, len(self._manifestation_audit)
            )
            max_live_name_records = max(max_live_name_records, len(self._name_records))
            max_live_connections = max(max_live_connections, len(self._connection_versions))
            max_archive_refs = max(max_archive_refs, len(self._recent_archive_references))

        for transition_index in range(transitions):
            world_tick = transition_index + 1
            operation = transition_index % 4
            if operation == 0:
                alias = aliases[memory_step % len(aliases)]
                memory_step += 1
                parent_id = latest_by_alias[alias]
                parent = self._memory_versions.get(parent_id)
                should_rewrite = parent is not None and rng.randrange(100) < 67
                if should_rewrite:
                    version = self.rewrite_memory(
                        memory_lineage_id=parent.memory_lineage_id,
                        parent_version_ids=(parent.memory_version_id,),
                        observation_ids=(observations[alias].observation_id,),
                        claim=claims[alias],
                        source_kind=SourceKind.EXPERIENCED,
                        initial_clarity_milli=850 + rng.randrange(151),
                        initial_emotion_residue=(),
                        created_tick=world_tick,
                        rewrite_reason_code="STRESS_REHEARSAL_REWRITE",
                    )
                else:
                    version = self.create_memory(
                        owner_id=owner_id,
                        observation_ids=(observations[alias].observation_id,),
                        claim=claims[alias],
                        source_kind=SourceKind.EXPERIENCED,
                        initial_clarity_milli=850 + rng.randrange(151),
                        initial_emotion_residue=(),
                        created_tick=world_tick,
                    )
                latest_by_alias[alias] = version.memory_version_id
                all_memory_ids.append(version.memory_version_id)
            elif operation == 1:
                alias = aliases[rng.randrange(len(aliases))]
                memory_id = latest_by_alias[alias]
                self.transition_memory(
                    memory_id,
                    mode=ForgettingMode.FACT_ONLY,
                    reason_code="STRESS_NIGHTLY_DECAY",
                    decay_per_night_milli=1 + rng.randrange(7),
                    explicit_penalty_milli=rng.randrange(3),
                    explicit_rehearsal_bonus_milli=rng.randrange(5),
                    world_tick=world_tick,
                )
            elif operation == 2:
                pending_alias = aliases[acknowledgement_count % len(aliases)]
                memory_id = latest_by_alias[pending_alias]
                memory = self.get_memory_version(memory_id)
                observation = observations[pending_alias]
                record = self.create_name_record(
                    NameRecordDraft(
                        source_memory_version_ids=(memory.memory_version_id,),
                        source_observation_ids=(observation.observation_id,),
                        source_family_ids=(observation.source_family_id,),
                        claim=memory.claim,
                        permission_level=PermissionLevel.L1_WITNESS,
                        confirmed_by_player=True,
                        consenting_actor_ids=(),
                        effective_from_tick=world_tick,
                        recognition_scope=RecognitionScope.HALL_LOCAL,
                        mitigation_plan_ids=("PLAN_PROSPECTIVE_REPLACEMENT",),
                        created_tick=world_tick,
                    )
                )
                pending_record_id = record.name_record_id
            else:
                if pending_record_id is None or pending_alias is None:
                    raise self._error(
                        MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN,
                        "stress schedule lost its pending NameRecord",
                        transition_index=transition_index,
                    )
                before_trace = len(self._history_trace)
                acknowledgement = self.acknowledge_name_record(
                    pending_record_id,
                    world_tick=world_tick,
                    manifestation_changes={
                        "stress_alias": pending_alias,
                        "stress_revision": acknowledgement_count + 1,
                    },
                    manifestation_rule_id="RULE_V070_SAME_WORLD_STRESS",
                )
                acknowledgement_count += 1
                if len(self._history_trace) <= before_trace:
                    partial_commits += 1
                if acknowledgement.created_connection_version_ids[0] not in self._connection_versions_by_id:
                    partial_commits += 1
                pending_record_id = None
                pending_alias = None

            # Exercise the bounded derived-query cache without changing the
            # authoritative state. Occasionally read an archived memory through
            # its Trace reference as well.
            self.query_memory(latest_by_alias[aliases[transition_index % 2]])
            if transition_index > 0 and transition_index % 113 == 0:
                self.query_memory(all_memory_ids[max(0, transition_index // 113 - 1)])

            for lineage_id, version_ids in self._lineage_versions.items():
                seen: set[str] = set()
                for version_id in version_ids:
                    if version_id in seen:
                        lineage_cycles += 1
                    seen.add(version_id)
                    version = self._memory_versions[version_id]
                    if version.memory_lineage_id != lineage_id:
                        lineage_cycles += 1
                    if any(parent_id == version_id for parent_id in version.parent_version_ids):
                        lineage_cycles += 1

            update_maxima()
            if (transition_index + 1) % 2500 == 0 or transition_index + 1 == transitions:
                expected = self.state_digest()
                try:
                    restored = self.load_state(self.save_state())
                    replayed = self.replay_digest()
                except MemoryKernelError:
                    digest_mismatches += 1
                else:
                    if restored.state_digest() != expected or replayed != expected:
                        digest_mismatches += 1

        if pending_record_id is not None:
            partial_commits += 1
        final_state_digest = self.state_digest()
        try:
            final_replay_digest = self.replay_digest()
        except MemoryKernelError:
            final_replay_digest = ""
            digest_mismatches += 1

        return StressSummary(
            transitions=transitions,
            max_active_lineages_per_actor=max_active_lineages,
            max_active_versions_per_lineage=max_versions_per_lineage,
            max_recent_forgetting_events=max_forgetting,
            max_recent_acknowledgements=max_acknowledgements,
            max_belief_query_cache_per_actor=max_query_cache,
            max_manifestation_audit_window=max_manifestation_audit,
            lineage_cycles=lineage_cycles,
            partial_commits=partial_commits,
            digest_mismatches=digest_mismatches,
            history_trace_records=len(self._history_trace),
            max_live_name_records=max_live_name_records,
            max_live_connection_versions=max_live_connections,
            max_recent_archive_references=max_archive_refs,
            archived_memory_versions=self._archived_memory_versions,
            archived_memory_lineages=self._archived_memory_lineages,
            final_state_digest=final_state_digest,
            final_replay_digest=final_replay_digest,
        )
