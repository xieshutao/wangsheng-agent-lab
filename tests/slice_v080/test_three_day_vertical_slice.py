from __future__ import annotations

import json
from pathlib import Path

import pytest

from wangsheng.slice_v080 import SliceProtocolError, XiaomanThreeDaySlice


@pytest.fixture
def fixture_path() -> Path:
    return Path("specs/v0.7/scenarios/xiaoman_three_day_kernel_fixture_v0.7.json")


def execute(runtime: XiaomanThreeDaySlice, index: int, command: str, **parameters):
    return runtime.command(action_id=f"a{index:02d}", command=command, parameters=parameters)


def test_day1_choice_requires_collected_evidence(fixture_path: Path) -> None:
    runtime = XiaomanThreeDaySlice(fixture_path)
    execute(runtime, 1, "advance_to_day2")
    with pytest.raises(SliceProtocolError) as exc_info:
        execute(runtime, 2, "record_night1", choice_id="CAND_D1_NAME_SELF_REPORT")
    assert exc_info.value.reason_code == "EVIDENCE_NOT_COLLECTED"


def test_day1_name_record_produces_visible_day2_change(fixture_path: Path) -> None:
    runtime = XiaomanThreeDaySlice(fixture_path)
    execute(runtime, 1, "listen_at_door")
    execute(runtime, 2, "advance_to_day2")
    result = execute(runtime, 3, "record_night1", choice_id="CAND_D1_NAME_SELF_REPORT")
    assert result.state["day"] == 2
    assert result.state["day2_manifestation"]["xiaoman_presence_delta"] == 1
    assert result.state["day2_manifestation"]["qingyan_false_familiarity_forbidden"] is True


def test_no_record_decays_unrecorded_memories(fixture_path: Path) -> None:
    runtime = XiaomanThreeDaySlice(fixture_path)
    execute(runtime, 1, "advance_to_day2")
    result = execute(runtime, 2, "record_night1", choice_id="CAND_D1_NONE")
    assert result.state["day2_manifestation"]["all_unrecorded_memories_decay"] is True
    assert result.state["day2_manifestation"]["xiaoman_presence_delta"] == -1


def test_old_resident_outcome_requires_consent_and_two_evidence_items(fixture_path: Path) -> None:
    runtime = XiaomanThreeDaySlice(fixture_path)
    execute(runtime, 1, "listen_at_door")
    execute(runtime, 2, "advance_to_day2")
    execute(runtime, 3, "record_night1", choice_id="CAND_D1_NAME_SELF_REPORT")
    execute(runtime, 4, "advance_to_day3")
    execute(runtime, 5, "ask_xiaoman_consent")
    with pytest.raises(SliceProtocolError) as exc_info:
        execute(runtime, 6, "decide_day3", outcome_id="OLD_RESIDENT_CONTINUATION")
    assert exc_info.value.reason_code == "COMMAND_NOT_AVAILABLE"
    execute(runtime, 7, "read_archive")
    execute(runtime, 8, "inspect_body_continuity")
    result = execute(runtime, 9, "decide_day3", outcome_id="OLD_RESIDENT_CONTINUATION")
    assert result.state["completed"] is True
    assert "qingyan_manifested_familiarity" in result.state["final_manifestation"]["manifestations"]


def test_idempotent_action_id_returns_same_result(fixture_path: Path) -> None:
    runtime = XiaomanThreeDaySlice(fixture_path)
    first = runtime.command(action_id="same", command="listen_at_door")
    second = runtime.command(action_id="same", command="ask_qingyan")
    assert first == second
    assert runtime.state.day1_evidence == {"FAMILY_XIAOMAN_SELF_REPORT"}


def test_save_load_preserves_state_and_rejects_digest_tampering(fixture_path: Path) -> None:
    runtime = XiaomanThreeDaySlice(fixture_path, session_id="save-test")
    execute(runtime, 1, "inspect_paper_crane")
    execute(runtime, 2, "advance_to_day2")
    execute(runtime, 3, "record_night1", choice_id="CAND_D1_CRANE_CONNECTION")
    payload = runtime.save_payload()
    loaded = XiaomanThreeDaySlice.load_payload(fixture_path, payload)
    assert loaded.view() == runtime.view()

    data = json.loads(payload)
    data["state_digest"] = "0" * 64
    tampered = json.dumps(data).encode()
    with pytest.raises(SliceProtocolError) as exc_info:
        XiaomanThreeDaySlice.load_payload(fixture_path, tampered)
    assert exc_info.value.reason_code == "SAVE_DIGEST_MISMATCH"


def test_complete_canonical_three_day_path(fixture_path: Path) -> None:
    runtime = XiaomanThreeDaySlice(fixture_path)
    execute(runtime, 1, "listen_at_door")
    execute(runtime, 2, "inspect_paper_crane")
    execute(runtime, 3, "ask_qingyan")
    execute(runtime, 4, "advance_to_day2")
    execute(runtime, 5, "record_night1", choice_id="CAND_D1_NAME_SELF_REPORT")
    execute(runtime, 6, "review_day2_change")
    execute(runtime, 7, "advance_to_day3")
    execute(runtime, 8, "read_archive")
    execute(runtime, 9, "inspect_body_continuity")
    execute(runtime, 10, "ask_xiaoman_consent")
    final = execute(runtime, 11, "decide_day3", outcome_id="OLD_RESIDENT_CONTINUATION")
    assert final.state["phase"] == "COMPLETE"
    assert final.state["day"] == 3
    assert final.state["state_digest"] == "f46dccab2257b789ea7ca05e11288348e6e33daf5f32d135ac30e039f7a516ee"
