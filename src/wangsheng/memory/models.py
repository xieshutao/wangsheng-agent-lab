from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any, Mapping


UNKNOWN = "UNKNOWN"
SCHEMA_VERSION = "0.7"


def freeze_value(value: Any) -> Any:
    """Recursively detach mutable caller-owned values from domain objects.

    The memory kernel treats committed facts, observations and memory content as
    immutable value objects. ``frozen=True`` alone is insufficient when a field
    contains a dict/list, so all nested containers are copied and frozen here.
    """

    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((freeze_value(item) for item in value), key=repr))
    return value


def primitive_value(value: Any) -> Any:
    """Convert domain values into canonical JSON-compatible primitives."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): primitive_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [primitive_value(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: primitive_value(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    return value


class SourceKind(StrEnum):
    EXPERIENCED = "EXPERIENCED"
    HEARD = "HEARD"
    READ = "READ"
    INFERRED = "INFERRED"
    DREAM = "DREAM"
    MANIFESTED = "MANIFESTED"


class AccessState(StrEnum):
    CLEAR = "CLEAR"
    FADED = "FADED"
    SUPPRESSED = "SUPPRESSED"
    FORGOTTEN = "FORGOTTEN"
    SEALED = "SEALED"


class VersionState(StrEnum):
    ACTIVE = "ACTIVE"
    CONTRADICTED = "CONTRADICTED"
    REWRITTEN = "REWRITTEN"
    SUPERSEDED = "SUPERSEDED"


class RecordStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class PermissionLevel(StrEnum):
    L1_WITNESS = "L1_WITNESS"
    L2_BELONGING = "L2_BELONGING"
    L3_LIMITED_CONTINUITY = "L3_LIMITED_CONTINUITY"
    L4_PUBLIC_INSTITUTION = "L4_PUBLIC_INSTITUTION"


class RecognitionScope(StrEnum):
    PRIVATE = "PRIVATE"
    HALL_LOCAL = "HALL_LOCAL"
    PUBLIC = "PUBLIC"


class Polarity(StrEnum):
    AFFIRM = "AFFIRM"
    DENY = "DENY"
    UNKNOWN = "UNKNOWN"


class ForgettingMode(StrEnum):
    FACT_ONLY = "FACT_ONLY"
    FACT_AND_EMOTION = "FACT_AND_EMOTION"
    REWRITE_WITH_RESIDUE = "REWRITE_WITH_RESIDUE"
    SUPPRESS = "SUPPRESS"
    UNSUPPRESS = "UNSUPPRESS"


class ConflictType(StrEnum):
    LOGICAL_EXCLUSION = "LOGICAL_EXCLUSION"
    PHYSICAL_EXCLUSIVITY = "PHYSICAL_EXCLUSIVITY"
    INSTITUTIONAL_EXCLUSIVITY = "INSTITUTIONAL_EXCLUSIVITY"
    DECLARED_CAPACITY_COMPETITION = "DECLARED_CAPACITY_COMPETITION"


class AcknowledgementOutcome(StrEnum):
    ESTABLISHED = "ESTABLISHED"
    STRENGTHENED = "STRENGTHENED"
    NARROWED = "NARROWED"
    PROSPECTIVELY_REPLACED = "PROSPECTIVELY_REPLACED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Claim:
    subject_id: str
    predicate: str
    object_id_or_value: Any
    time_scope: str
    recognition_scope: RecognitionScope
    polarity: Polarity = Polarity.AFFIRM
    qualifiers: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "object_id_or_value", freeze_value(self.object_id_or_value))
        object.__setattr__(self, "qualifiers", freeze_value(self.qualifiers))


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    event_id: str
    sequence: int
    world_tick: int
    event_type: str
    actor_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    location_id: str
    payload: Mapping[str, Any]
    caused_by_action_id: str | None
    schema_version: str
    event_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_ids", tuple(self.actor_ids))
        object.__setattr__(self, "target_ids", tuple(self.target_ids))
        object.__setattr__(self, "payload", freeze_value(self.payload))


@dataclass(frozen=True, slots=True)
class ObservationDraft:
    observer_id: str
    source_kind: SourceKind
    source_event_ids: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    source_actor_id: str | None
    source_evidence_id: str | None
    source_family_id: str
    claim: Claim
    confidence_milli: int
    acquired_tick: int
    world_version_seen: int
    derived_from_acknowledgement_id: str | None = None
    inference_rule_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        object.__setattr__(self, "source_observation_ids", tuple(self.source_observation_ids))


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    observer_id: str
    source_kind: SourceKind
    source_event_ids: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    source_actor_id: str | None
    source_evidence_id: str | None
    source_family_id: str
    claim: Claim
    confidence_milli: int
    acquired_tick: int
    world_version_seen: int
    derived_from_acknowledgement_id: str | None = None
    inference_rule_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        object.__setattr__(self, "source_observation_ids", tuple(self.source_observation_ids))


@dataclass(frozen=True, slots=True)
class EmotionalResidue:
    emotion_type: str
    intensity_milli: int
    target_id: str
    origin_memory_version_id: str | None
    decay_per_night_milli: int
    access_independent: bool


@dataclass(frozen=True, slots=True)
class MemoryVersion:
    memory_lineage_id: str
    memory_version_id: str
    version_no: int
    owner_id: str
    parent_version_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    claim: Claim
    source_kind: SourceKind
    initial_clarity_milli: int
    initial_emotion_residue: tuple[EmotionalResidue, ...]
    created_tick: int
    rewrite_reason_code: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parent_version_ids", tuple(self.parent_version_ids))
        object.__setattr__(self, "observation_ids", tuple(self.observation_ids))
        object.__setattr__(self, "initial_emotion_residue", tuple(self.initial_emotion_residue))


@dataclass(frozen=True, slots=True)
class MemoryStateSnapshot:
    memory_version_id: str
    state_revision: int
    access_state: AccessState
    version_state: VersionState
    clarity_milli: int
    emotion_residue: tuple[EmotionalResidue, ...]
    last_transition_event_id: str
    last_transition_tick: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "emotion_residue", tuple(self.emotion_residue))


@dataclass(frozen=True, slots=True)
class ForgettingEvent:
    forgetting_event_id: str
    target_memory_version_id: str
    previous_state_revision: int
    new_state_revision: int
    mode: ForgettingMode
    reason_code: str
    before_clarity_milli: int
    after_clarity_milli: int
    before_access_state: AccessState
    after_access_state: AccessState
    emotion_deltas: tuple[EmotionalResidue, ...]
    world_tick: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "emotion_deltas", tuple(self.emotion_deltas))


@dataclass(frozen=True, slots=True)
class MemoryQueryResult:
    memory_version_id: str
    access_state: AccessState
    version_state: VersionState
    claim: Claim | None
    emotion_residue: tuple[EmotionalResidue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "emotion_residue", tuple(self.emotion_residue))


@dataclass(frozen=True, slots=True)
class NameRecordDraft:
    source_memory_version_ids: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    source_family_ids: tuple[str, ...]
    claim: Claim
    permission_level: PermissionLevel
    confirmed_by_player: bool
    consenting_actor_ids: tuple[str, ...]
    effective_from_tick: int
    recognition_scope: RecognitionScope
    mitigation_plan_ids: tuple[str, ...]
    created_tick: int
    parent_acknowledgement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_memory_version_ids", tuple(self.source_memory_version_ids))
        object.__setattr__(self, "source_observation_ids", tuple(self.source_observation_ids))
        object.__setattr__(self, "source_family_ids", tuple(self.source_family_ids))
        object.__setattr__(self, "consenting_actor_ids", tuple(self.consenting_actor_ids))
        object.__setattr__(self, "mitigation_plan_ids", tuple(self.mitigation_plan_ids))
        object.__setattr__(self, "parent_acknowledgement_ids", tuple(self.parent_acknowledgement_ids))


@dataclass(frozen=True, slots=True)
class NameRecord:
    name_record_id: str
    source_memory_version_ids: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    source_family_ids: tuple[str, ...]
    claim: Claim
    permission_level: PermissionLevel
    record_status: RecordStatus
    confirmed_by_player: bool
    consenting_actor_ids: tuple[str, ...]
    effective_from_tick: int
    recognition_scope: RecognitionScope
    mitigation_plan_ids: tuple[str, ...]
    created_tick: int
    parent_acknowledgement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_memory_version_ids", tuple(self.source_memory_version_ids))
        object.__setattr__(self, "source_observation_ids", tuple(self.source_observation_ids))
        object.__setattr__(self, "source_family_ids", tuple(self.source_family_ids))
        object.__setattr__(self, "consenting_actor_ids", tuple(self.consenting_actor_ids))
        object.__setattr__(self, "mitigation_plan_ids", tuple(self.mitigation_plan_ids))
        object.__setattr__(self, "parent_acknowledgement_ids", tuple(self.parent_acknowledgement_ids))


@dataclass(frozen=True, slots=True)
class MemoryConflict:
    conflict_id: str
    conflict_type: ConflictType
    candidate_ids: tuple[str, ...]
    resource_key: str
    detected_tick: int
    required_mitigation_types: tuple[str, ...]
    resolution_status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_ids", tuple(self.candidate_ids))
        object.__setattr__(self, "required_mitigation_types", tuple(self.required_mitigation_types))


@dataclass(frozen=True, slots=True)
class ConnectionVersion:
    connection_lineage_id: str
    connection_version_id: str
    version_no: int
    claim: Claim
    status: str
    based_on_name_record_id: str
    effective_from_tick: int
    effective_until_tick: int | None
    scope: RecognitionScope
    supersedes_connection_version_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "supersedes_connection_version_ids", tuple(self.supersedes_connection_version_ids))


@dataclass(frozen=True, slots=True)
class ManifestationDelta:
    manifestation_delta_id: str
    acknowledgement_id: str
    target_state_path: str
    before_value: Any
    after_value: Any
    derivation_rule_id: str
    derived_evidence_family_id: str
    applied_tick: int


@dataclass(frozen=True, slots=True)
class WorldAcknowledgement:
    acknowledgement_id: str
    name_record_id: str
    outcome: AcknowledgementOutcome
    created_connection_version_ids: tuple[str, ...]
    superseded_connection_version_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    manifestation_delta_ids: tuple[str, ...]
    audit_reasons: tuple[str, ...]
    world_tick: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_connection_version_ids", tuple(self.created_connection_version_ids))
        object.__setattr__(self, "superseded_connection_version_ids", tuple(self.superseded_connection_version_ids))
        object.__setattr__(self, "conflict_ids", tuple(self.conflict_ids))
        object.__setattr__(self, "manifestation_delta_ids", tuple(self.manifestation_delta_ids))
        object.__setattr__(self, "audit_reasons", tuple(self.audit_reasons))


@dataclass(frozen=True, slots=True)
class KernelConfig:
    active_memory_lineages_per_actor: int = 256
    active_memory_versions_per_lineage: int = 4
    recent_forgetting_events_cache: int = 256
    recent_acknowledgement_cache: int = 128
    belief_query_cache_per_actor: int = 128
    manifestation_audit_window: int = 128
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class BranchResult:
    branch_id: str
    occurrence_digest: str
    state_digest: str
    manifestation_state: Mapping[str, Any]
    active_connection_claims: tuple[Claim, ...]


@dataclass(frozen=True, slots=True)
class ReplayVerification:
    checkpoints: int
    snapshot_digest: str
    replay_digest: str
    state_match: bool
    branch_digests: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class StressSummary:
    transitions: int
    max_active_lineages_per_actor: int
    max_active_versions_per_lineage: int
    max_recent_forgetting_events: int
    max_recent_acknowledgements: int
    max_belief_query_cache_per_actor: int
    max_manifestation_audit_window: int
    lineage_cycles: int
    partial_commits: int
    digest_mismatches: int
    history_trace_records: int
