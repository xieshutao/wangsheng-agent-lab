from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import (
    AcknowledgementOutcome,
    BranchResult,
    CanonicalEvent,
    Claim,
    EmotionalResidue,
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
    StressSummary,
    WorldAcknowledgement,
)


P1_NOT_IMPLEMENTED = "V0.7_P1_CONTRACT_ONLY"


class MemoryVersioningKernel:
    """Public façade frozen by v0.7 P1.

    P1 intentionally contains no domain behavior. Every operation raises the same
    marker ``NotImplementedError`` so the 20 executable contract tests are red for
    one controlled reason. P2-P5 replace these stubs incrementally without
    weakening the tests.
    """

    def __init__(self, config: KernelConfig | None = None) -> None:
        self.config = config or KernelConfig()

    @staticmethod
    def _missing() -> None:
        raise NotImplementedError(P1_NOT_IMPLEMENTED)

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
        self._missing()

    def get_event(self, event_id: str) -> CanonicalEvent:
        self._missing()

    def list_events(self) -> tuple[CanonicalEvent, ...]:
        self._missing()

    def replace_event(self, event_id: str, *, payload: Mapping[str, Any]) -> None:
        self._missing()

    def delete_event(self, event_id: str) -> None:
        self._missing()

    def occurrence_digest(self) -> str:
        self._missing()

    def record_observation(
        self,
        draft: ObservationDraft,
        *,
        authorized_claim: Claim,
    ) -> Observation:
        self._missing()

    def create_memory(
        self,
        *,
        owner_id: str,
        observation_ids: Sequence[str],
        claim: Claim,
        source_kind: str,
        initial_clarity_milli: int,
        initial_emotion_residue: Sequence[EmotionalResidue],
        created_tick: int,
        memory_lineage_id: str | None = None,
        parent_version_ids: Sequence[str] = (),
        rewrite_reason_code: str | None = None,
    ) -> MemoryVersion:
        self._missing()

    def rewrite_memory(
        self,
        *,
        memory_lineage_id: str,
        parent_version_ids: Sequence[str],
        observation_ids: Sequence[str],
        claim: Claim,
        source_kind: str,
        initial_clarity_milli: int,
        initial_emotion_residue: Sequence[EmotionalResidue],
        created_tick: int,
        rewrite_reason_code: str,
    ) -> MemoryVersion:
        self._missing()

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
        self._missing()

    def get_memory_state(self, memory_version_id: str) -> MemoryStateSnapshot:
        self._missing()

    def query_memory(self, memory_version_id: str) -> MemoryQueryResult:
        self._missing()

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
        outcome: AcknowledgementOutcome,
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
