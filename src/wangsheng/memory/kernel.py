from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .errors import MemoryErrorCode, MemoryKernelError
from .models import (
    AccessState,
    BranchResult,
    CanonicalEvent,
    Claim,
    EmotionalResidue,
    ForgettingEvent,
    ForgettingMode,
    KernelConfig,
    MemoryQueryResult,
    MemoryStateSnapshot,
    MemoryVersion,
    NameRecord,
    NameRecordDraft,
    Observation,
    ObservationDraft,
    ReplayVerification,
    SourceKind,
    StressSummary,
    VersionState,
    WorldAcknowledgement,
    primitive_value,
)


P1_NOT_IMPLEMENTED = "V0.7_P1_CONTRACT_ONLY"


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
        self._history_trace: list[Mapping[str, Any]] = []
        self._id_counters: dict[str, int] = defaultdict(int)

    @staticmethod
    def _missing() -> None:
        raise NotImplementedError(P1_NOT_IMPLEMENTED)

    def _next_id(self, prefix: str) -> str:
        self._id_counters[prefix] += 1
        return f"{prefix}.v070.{self._id_counters[prefix]:08d}"

    def _append_trace(self, kind: str, payload: Mapping[str, Any]) -> None:
        self._history_trace.append(
            MappingProxyType(
                {
                    "sequence": len(self._history_trace) + 1,
                    "kind": kind,
                    "payload": primitive_value(payload),
                }
            )
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
        self._memory_versions[memory_version_id] = version
        self._memory_states[memory_version_id] = state
        self._lineage_versions[lineage_id].append(memory_version_id)
        self._append_trace("MEMORY_VERSION_CREATED", {"memory_version": version, "state": state})
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
        return self._create_memory_version(
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
            self._append_trace(
                "MEMORY_VERSION_REWRITTEN",
                {"parent_memory_version_id": parent_id, "new_memory_version_id": version.memory_version_id},
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
        self._forgetting_events.append(forgetting_event)
        self._append_trace(
            "FORGETTING_EVENT_APPLIED",
            {"forgetting_event": forgetting_event, "new_state": new_state},
        )
        return new_state

    def get_memory_version(self, memory_version_id: str) -> MemoryVersion:
        try:
            return self._memory_versions[memory_version_id]
        except KeyError as exc:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory version does not exist",
                memory_version_id=memory_version_id,
            ) from exc

    def get_memory_state(self, memory_version_id: str) -> MemoryStateSnapshot:
        try:
            return self._memory_states[memory_version_id]
        except KeyError as exc:
            raise self._error(
                MemoryErrorCode.MEMORY_UNKNOWN_SOURCE,
                "memory state does not exist",
                memory_version_id=memory_version_id,
            ) from exc

    def list_forgetting_events(self) -> tuple[ForgettingEvent, ...]:
        return tuple(self._forgetting_events)

    def query_memory(self, memory_version_id: str) -> MemoryQueryResult:
        version = self.get_memory_version(memory_version_id)
        state = self.get_memory_state(memory_version_id)
        accessible = state.access_state in (AccessState.CLEAR, AccessState.FADED)
        residues = state.emotion_residue
        if state.access_state == AccessState.FORGOTTEN:
            residues = tuple(item for item in residues if item.access_independent)
        return MemoryQueryResult(
            memory_version_id=memory_version_id,
            access_state=state.access_state,
            version_state=state.version_state,
            claim=version.claim if accessible else None,
            emotion_residue=residues,
        )

    def register_contradiction(
        self,
        memory_version_ids: Sequence[str],
        *,
        detected_tick: int,
    ) -> tuple[MemoryStateSnapshot, ...]:
        self._missing()

    def create_name_record(self, draft: NameRecordDraft) -> NameRecord:
        self._missing()

    def get_name_record(self, name_record_id: str) -> NameRecord:
        self._missing()

    def acknowledge_name_record(
        self,
        name_record_id: str,
        *,
        world_tick: int,
    ) -> WorldAcknowledgement:
        self._missing()

    def active_connection_claims(self) -> tuple[Claim, ...]:
        self._missing()

    def manifestation_state(self) -> Mapping[str, Any]:
        self._missing()

    def state_digest(self) -> str:
        self._missing()

    def save_state(self) -> bytes:
        self._missing()

    @classmethod
    def load_state(cls, payload: bytes) -> "MemoryVersioningKernel":
        cls._missing()

    def replay_digest(self) -> str:
        self._missing()

    @classmethod
    def run_xiaoman_day1_branches(cls, fixture_path: Path) -> Mapping[str, BranchResult]:
        cls._missing()

    @classmethod
    def run_xiaoman_day3_outcomes(cls, fixture_path: Path) -> Mapping[str, BranchResult]:
        cls._missing()

    @classmethod
    def verify_xiaoman_save_load_replay(cls, fixture_path: Path) -> ReplayVerification:
        cls._missing()

    def run_same_world_stress(self, *, transitions: int, seed: int) -> StressSummary:
        self._missing()
