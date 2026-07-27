from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping


SLICE_SCHEMA_VERSION = "0.8-slice"


class SlicePhase(StrEnum):
    DAY1_INVESTIGATION = "DAY1_INVESTIGATION"
    NIGHT1_RECORD = "NIGHT1_RECORD"
    DAY2_CONSEQUENCE = "DAY2_CONSEQUENCE"
    DAY3_INVESTIGATION = "DAY3_INVESTIGATION"
    DAY3_DECISION = "DAY3_DECISION"
    COMPLETE = "COMPLETE"


class SliceCommand(StrEnum):
    LISTEN_AT_DOOR = "listen_at_door"
    INSPECT_PAPER_CRANE = "inspect_paper_crane"
    ASK_QINGYAN = "ask_qingyan"
    REVIEW_DAY1_EVIDENCE = "review_day1_evidence"
    RECORD_NIGHT1 = "record_night1"
    ADVANCE_TO_DAY2 = "advance_to_day2"
    REVIEW_DAY2_CHANGE = "review_day2_change"
    ADVANCE_TO_DAY3 = "advance_to_day3"
    READ_ARCHIVE = "read_archive"
    INSPECT_BODY_CONTINUITY = "inspect_body_continuity"
    ASK_XIAOMAN_CONSENT = "ask_xiaoman_consent"
    REVIEW_DAY3_EVIDENCE = "review_day3_evidence"
    DECIDE_DAY3 = "decide_day3"
    SAVE = "save"


@dataclass(frozen=True, slots=True)
class CommandResult:
    action_id: str
    status: str
    reason_code: str
    message: str
    state: Mapping[str, Any]
    observations: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SliceSessionState:
    session_id: str
    schema_version: str = SLICE_SCHEMA_VERSION
    day: int = 1
    phase: SlicePhase = SlicePhase.DAY1_INVESTIGATION
    world_tick: int = 1
    day1_evidence: set[str] = field(default_factory=set)
    night1_choice: str | None = None
    day2_manifestation: dict[str, Any] = field(default_factory=dict)
    day3_evidence: set[str] = field(default_factory=set)
    xiaoman_consented: bool = False
    day3_outcome: str | None = None
    final_manifestation: dict[str, Any] = field(default_factory=dict)
    occurrence_digest: str | None = None
    state_digest: str | None = None
    completed: bool = False
    processed_actions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def public_view(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "schema_version": self.schema_version,
            "day": self.day,
            "phase": self.phase.value,
            "world_tick": self.world_tick,
            "day1_evidence": sorted(self.day1_evidence),
            "night1_choice": self.night1_choice,
            "day2_manifestation": dict(self.day2_manifestation),
            "day3_evidence": sorted(self.day3_evidence),
            "xiaoman_consented": self.xiaoman_consented,
            "day3_outcome": self.day3_outcome,
            "final_manifestation": dict(self.final_manifestation),
            "occurrence_digest": self.occurrence_digest,
            "state_digest": self.state_digest,
            "completed": self.completed,
        }
