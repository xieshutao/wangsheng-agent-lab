from __future__ import annotations

import json
import uuid
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from wangsheng.memory import MemoryVersioningKernel

from .models import CommandResult, SliceCommand, SlicePhase, SliceSessionState


DAY1_CHOICES = {
    "CAND_D1_NAME_SELF_REPORT",
    "CAND_D1_CRANE_CONNECTION",
    "CAND_D1_QINGYAN_UNKNOWN",
    "CAND_D1_NONE",
}

DAY3_OUTCOMES = {
    "OLD_RESIDENT_CONTINUATION",
    "NEW_PERSON_USING_NAME",
    "NAME_ONLY_HISTORY_UNRESOLVED",
    "REFUSED",
}

_DAY1_ACTION_EVIDENCE = {
    SliceCommand.LISTEN_AT_DOOR: "FAMILY_XIAOMAN_SELF_REPORT",
    SliceCommand.INSPECT_PAPER_CRANE: "FAMILY_PAPER_CRANE_OLD_NETWORK",
    SliceCommand.ASK_QINGYAN: "FAMILY_QINGYAN_SELF_REPORT",
}

_DAY3_ACTION_EVIDENCE = {
    SliceCommand.READ_ARCHIVE: "TEN_YEAR_OLD_DEATH_RECORD",
    SliceCommand.INSPECT_BODY_CONTINUITY: "BODY_CONTINUITY_SUPPORTED",
}


class SliceProtocolError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class XiaomanThreeDaySlice:
    """Deterministic orchestration layer for the first playable vertical slice.

    The v0.7 memory kernel remains authoritative. This layer owns only the
    three-day player-facing progression, evidence unlocks, idempotent commands,
    save/load, and the compact state envelope intended for a UE client.
    """

    def __init__(self, fixture_path: Path, *, session_id: str | None = None) -> None:
        self.fixture_path = Path(fixture_path)
        self._fixture = MemoryVersioningKernel._load_xiaoman_fixture(self.fixture_path)
        self._day1_results = MemoryVersioningKernel.run_xiaoman_day1_branches(self.fixture_path)
        self._day3_results = MemoryVersioningKernel.run_xiaoman_day3_outcomes(self.fixture_path)
        self.state = SliceSessionState(session_id=session_id or f"slice-{uuid.uuid4().hex[:12]}")
        self._processed: OrderedDict[str, CommandResult] = OrderedDict()

    @property
    def session_id(self) -> str:
        return self.state.session_id

    def view(self) -> dict[str, Any]:
        view = self.state.public_view()
        view["available_commands"] = self.available_commands()
        view["available_night1_choices"] = self.available_night1_choices()
        view["available_day3_outcomes"] = self.available_day3_outcomes()
        return view

    def available_commands(self) -> list[str]:
        phase = self.state.phase
        mapping = {
            SlicePhase.DAY1_INVESTIGATION: [
                SliceCommand.LISTEN_AT_DOOR,
                SliceCommand.INSPECT_PAPER_CRANE,
                SliceCommand.ASK_QINGYAN,
                SliceCommand.REVIEW_DAY1_EVIDENCE,
                SliceCommand.ADVANCE_TO_DAY2,
            ],
            SlicePhase.NIGHT1_RECORD: [
                SliceCommand.REVIEW_DAY1_EVIDENCE,
                SliceCommand.RECORD_NIGHT1,
            ],
            SlicePhase.DAY2_CONSEQUENCE: [
                SliceCommand.REVIEW_DAY2_CHANGE,
                SliceCommand.ADVANCE_TO_DAY3,
            ],
            SlicePhase.DAY3_INVESTIGATION: [
                SliceCommand.READ_ARCHIVE,
                SliceCommand.INSPECT_BODY_CONTINUITY,
                SliceCommand.ASK_XIAOMAN_CONSENT,
                SliceCommand.REVIEW_DAY3_EVIDENCE,
            ],
            SlicePhase.DAY3_DECISION: [
                SliceCommand.READ_ARCHIVE,
                SliceCommand.INSPECT_BODY_CONTINUITY,
                SliceCommand.ASK_XIAOMAN_CONSENT,
                SliceCommand.REVIEW_DAY3_EVIDENCE,
                SliceCommand.DECIDE_DAY3,
            ],
            SlicePhase.COMPLETE: [SliceCommand.SAVE],
        }
        return [item.value for item in mapping[phase]]

    def available_night1_choices(self) -> list[str]:
        choices = ["CAND_D1_NONE"]
        if "FAMILY_XIAOMAN_SELF_REPORT" in self.state.day1_evidence:
            choices.append("CAND_D1_NAME_SELF_REPORT")
        if "FAMILY_PAPER_CRANE_OLD_NETWORK" in self.state.day1_evidence:
            choices.append("CAND_D1_CRANE_CONNECTION")
        if "FAMILY_QINGYAN_SELF_REPORT" in self.state.day1_evidence:
            choices.append("CAND_D1_QINGYAN_UNKNOWN")
        return choices

    def available_day3_outcomes(self) -> list[str]:
        if self.state.phase not in (SlicePhase.DAY3_INVESTIGATION, SlicePhase.DAY3_DECISION):
            return []
        outcomes = ["REFUSED"]
        if self.state.xiaoman_consented:
            outcomes.extend(["NEW_PERSON_USING_NAME", "NAME_ONLY_HISTORY_UNRESOLVED"])
            if {
                "TEN_YEAR_OLD_DEATH_RECORD",
                "BODY_CONTINUITY_SUPPORTED",
            }.issubset(self.state.day3_evidence):
                outcomes.append("OLD_RESIDENT_CONTINUATION")
        return outcomes

    def command(
        self,
        *,
        action_id: str,
        command: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> CommandResult:
        if not action_id or len(action_id) > 128:
            raise SliceProtocolError("INVALID_ACTION_ID", "action_id must be non-empty and <=128 chars")
        if action_id in self._processed:
            return self._processed[action_id]
        try:
            parsed = SliceCommand(command)
        except ValueError as exc:
            raise SliceProtocolError("UNKNOWN_COMMAND", f"unknown command: {command}") from exc
        if parsed.value not in self.available_commands():
            raise SliceProtocolError(
                "COMMAND_NOT_AVAILABLE",
                f"{parsed.value} is not available during {self.state.phase.value}",
            )
        result = self._execute(action_id=action_id, command=parsed, parameters=dict(parameters or {}))
        self._remember_result(result)
        return result

    def _remember_result(self, result: CommandResult) -> None:
        self._processed[result.action_id] = result
        while len(self._processed) > 128:
            self._processed.popitem(last=False)
        self.state.processed_actions = {
            action_id: item.to_dict() for action_id, item in self._processed.items()
        }

    def _result(
        self,
        *,
        action_id: str,
        message: str,
        observations: tuple[Mapping[str, Any], ...] = (),
    ) -> CommandResult:
        return CommandResult(
            action_id=action_id,
            status="SUCCESS",
            reason_code="NONE",
            message=message,
            observations=observations,
            state=self.view(),
        )

    def _execute(
        self,
        *,
        action_id: str,
        command: SliceCommand,
        parameters: Mapping[str, Any],
    ) -> CommandResult:
        if command in _DAY1_ACTION_EVIDENCE:
            evidence = _DAY1_ACTION_EVIDENCE[command]
            self.state.day1_evidence.add(evidence)
            self.state.world_tick += 1
            messages = {
                SliceCommand.LISTEN_AT_DOOR: "门外的孩子隔门自称‘小满’；这只是自我陈述，不证明旧身份。",
                SliceCommand.INSPECT_PAPER_CRANE: "纸鹤与往生堂旧网络存在可审计连接，但不能独立证明归属。",
                SliceCommand.ASK_QINGYAN: "清砚明确说自己记不清这个孩子；这不等于她没有过去。",
            }
            return self._result(
                action_id=action_id,
                message=messages[command],
                observations=({"evidence_family": evidence},),
            )

        if command == SliceCommand.REVIEW_DAY1_EVIDENCE:
            return self._result(
                action_id=action_id,
                message="已整理第一日证据。",
                observations=tuple({"evidence_family": item} for item in sorted(self.state.day1_evidence)),
            )

        if command == SliceCommand.ADVANCE_TO_DAY2:
            if self.state.phase == SlicePhase.DAY1_INVESTIGATION:
                self.state.phase = SlicePhase.NIGHT1_RECORD
                self.state.world_tick = 10
                return self._result(action_id=action_id, message="夜幕降临，请选择今晚唯一进入对照的记录。")
            raise SliceProtocolError("INVALID_PHASE", "cannot advance to day 2 from current phase")

        if command == SliceCommand.RECORD_NIGHT1:
            choice = str(parameters.get("choice_id", ""))
            if choice not in DAY1_CHOICES:
                raise SliceProtocolError("INVALID_CHOICE", "unknown night-1 choice")
            if choice not in self.available_night1_choices():
                raise SliceProtocolError("EVIDENCE_NOT_COLLECTED", "night-1 choice is not supported by collected evidence")
            result = self._day1_results[choice]
            self.state.night1_choice = choice
            self.state.day2_manifestation = dict(result.manifestation_state)
            self.state.occurrence_digest = result.occurrence_digest
            self.state.state_digest = result.state_digest
            self.state.day = 2
            self.state.phase = SlicePhase.DAY2_CONSEQUENCE
            self.state.world_tick = 20
            return self._result(
                action_id=action_id,
                message="留名结算完成。第二日的房间与人物状态已由确定性规则生成。",
                observations=({"manifestation": dict(result.manifestation_state)},),
            )

        if command == SliceCommand.REVIEW_DAY2_CHANGE:
            return self._result(
                action_id=action_id,
                message="第二日变化可追溯到昨夜记录；过去发生的敲门与自称事件没有被改写。",
                observations=({"manifestation": dict(self.state.day2_manifestation)},),
            )

        if command == SliceCommand.ADVANCE_TO_DAY3:
            self.state.day = 3
            self.state.phase = SlicePhase.DAY3_INVESTIGATION
            self.state.world_tick = 21
            return self._result(action_id=action_id, message="第三日开始。旧档案与身体连续性成为新的调查对象。")

        if command in _DAY3_ACTION_EVIDENCE:
            evidence = _DAY3_ACTION_EVIDENCE[command]
            self.state.day3_evidence.add(evidence)
            self.state.world_tick += 1
            messages = {
                SliceCommand.READ_ARCHIVE: "档案保留十年前的死亡事件；记录不能被普通留名删除。",
                SliceCommand.INSPECT_BODY_CONTINUITY: "当前身体连续性获得支持，但仍不能单独证明全部旧身份。",
            }
            if self.state.xiaoman_consented and self.state.day3_evidence:
                self.state.phase = SlicePhase.DAY3_DECISION
            return self._result(
                action_id=action_id,
                message=messages[command],
                observations=({"evidence": evidence},),
            )

        if command == SliceCommand.ASK_XIAOMAN_CONSENT:
            self.state.xiaoman_consented = True
            self.state.world_tick += 1
            if self.state.day3_evidence:
                self.state.phase = SlicePhase.DAY3_DECISION
            return self._result(
                action_id=action_id,
                message="小满同意由玩家决定她从今日起在堂内被怎样承认；这不等于同意改写过去。",
                observations=({"consent": True},),
            )

        if command == SliceCommand.REVIEW_DAY3_EVIDENCE:
            return self._result(
                action_id=action_id,
                message="已整理第三日证据与可用结算。",
                observations=(
                    {"evidence": sorted(self.state.day3_evidence)},
                    {"xiaoman_consented": self.state.xiaoman_consented},
                    {"available_outcomes": self.available_day3_outcomes()},
                ),
            )

        if command == SliceCommand.DECIDE_DAY3:
            outcome_id = str(parameters.get("outcome_id", ""))
            if outcome_id not in DAY3_OUTCOMES:
                raise SliceProtocolError("INVALID_OUTCOME", "unknown day-3 outcome")
            if outcome_id not in self.available_day3_outcomes():
                raise SliceProtocolError("OUTCOME_PREREQUISITES_NOT_MET", "day-3 outcome prerequisites are not met")
            result = self._day3_results[outcome_id]
            self.state.day3_outcome = outcome_id
            self.state.final_manifestation = dict(result.manifestation_state)
            self.state.occurrence_digest = result.occurrence_digest
            self.state.state_digest = result.state_digest
            self.state.phase = SlicePhase.COMPLETE
            self.state.world_tick = 30
            self.state.completed = True
            return self._result(
                action_id=action_id,
                message="三日结算完成。新连接与空间显现已生成，既有发生史保持不变。",
                observations=({"manifestation": dict(result.manifestation_state)},),
            )

        if command == SliceCommand.SAVE:
            return self._result(action_id=action_id, message="会话可通过 save_payload() 持久化。")

        raise SliceProtocolError("UNIMPLEMENTED_COMMAND", command.value)

    def save_payload(self) -> bytes:
        payload = self.state.public_view()
        payload["processed_actions"] = {
            action_id: result.to_dict() for action_id, result in self._processed.items()
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def load_payload(cls, fixture_path: Path, payload: bytes) -> "XiaomanThreeDaySlice":
        data = json.loads(payload.decode("utf-8"))
        runtime = cls(fixture_path, session_id=str(data["session_id"]))
        state = runtime.state
        state.schema_version = str(data["schema_version"])
        state.day = int(data["day"])
        state.phase = SlicePhase(data["phase"])
        state.world_tick = int(data["world_tick"])
        state.day1_evidence = set(data.get("day1_evidence", ()))
        state.night1_choice = data.get("night1_choice")
        state.day2_manifestation = dict(data.get("day2_manifestation", {}))
        state.day3_evidence = set(data.get("day3_evidence", ()))
        state.xiaoman_consented = bool(data.get("xiaoman_consented", False))
        state.day3_outcome = data.get("day3_outcome")
        state.final_manifestation = dict(data.get("final_manifestation", {}))
        state.occurrence_digest = data.get("occurrence_digest")
        state.state_digest = data.get("state_digest")
        state.completed = bool(data.get("completed", False))
        for action_id, result_data in data.get("processed_actions", {}).items():
            result = CommandResult(
                action_id=str(result_data["action_id"]),
                status=str(result_data["status"]),
                reason_code=str(result_data["reason_code"]),
                message=str(result_data["message"]),
                state=dict(result_data["state"]),
                observations=tuple(result_data.get("observations", ())),
            )
            runtime._processed[str(action_id)] = result
        runtime._remember_loaded_results()
        runtime._validate_loaded_digests()
        return runtime

    def _remember_loaded_results(self) -> None:
        while len(self._processed) > 128:
            self._processed.popitem(last=False)
        self.state.processed_actions = {
            action_id: item.to_dict() for action_id, item in self._processed.items()
        }

    def _validate_loaded_digests(self) -> None:
        if self.state.day3_outcome:
            expected = self._day3_results[self.state.day3_outcome]
        elif self.state.night1_choice:
            expected = self._day1_results[self.state.night1_choice]
        else:
            return
        if self.state.state_digest != expected.state_digest:
            raise SliceProtocolError("SAVE_DIGEST_MISMATCH", "saved state digest does not match frozen kernel result")
        if self.state.occurrence_digest != expected.occurrence_digest:
            raise SliceProtocolError("SAVE_DIGEST_MISMATCH", "saved occurrence digest does not match frozen kernel result")
