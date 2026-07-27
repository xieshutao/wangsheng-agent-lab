from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from wangsheng.memory import (
    Claim,
    KernelConfig,
    MemoryErrorCode,
    MemoryKernelError,
    MemoryVersioningKernel,
    NameRecordDraft,
    PermissionLevel,
    RecognitionScope,
)

from .helpers import claim


def _fixture(kernel_cls=MemoryVersioningKernel):
    return kernel_cls._load_xiaoman_fixture(  # noqa: SLF001 - phase-internal audit
        __import__("pathlib").Path("specs/v0.7/scenarios/xiaoman_three_day_kernel_fixture_v0.7.json")
    )


def test_p4_manifestation_state_is_deeply_detached_and_immutable() -> None:
    fixture = _fixture()
    kernel, _ = MemoryVersioningKernel._build_xiaoman_day3_branch(  # noqa: SLF001
        fixture, "OLD_RESIDENT_CONTINUATION"
    )
    state = kernel.manifestation_state()
    assert tuple(state["manifestations"])
    with pytest.raises(TypeError):
        state["manifestations"] = ()  # type: ignore[index]


def test_p4_manifestation_deltas_are_attached_to_acknowledgement_and_bounded() -> None:
    fixture = _fixture()
    kernel, _ = MemoryVersioningKernel._build_xiaoman_day3_branch(  # noqa: SLF001
        fixture, "NEW_PERSON_USING_NAME"
    )
    acknowledgement = next(iter(kernel._acknowledgements_by_id.values()))  # noqa: SLF001
    assert len(acknowledgement.manifestation_delta_ids) == 3
    assert tuple(item.manifestation_delta_id for item in kernel._manifestation_audit) == (  # noqa: SLF001
        acknowledgement.manifestation_delta_ids
    )
    assert all(
        item.derived_evidence_family_id == f"FAMILY_DERIVED_{acknowledgement.acknowledgement_id}"
        for item in kernel._manifestation_audit  # noqa: SLF001
    )


def test_p4_save_is_canonical_and_byte_stable() -> None:
    fixture = _fixture()
    kernel, _ = MemoryVersioningKernel._build_xiaoman_day3_branch(  # noqa: SLF001
        fixture, "NAME_ONLY_HISTORY_UNRESOLVED"
    )
    first = kernel.save_state()
    second = kernel.save_state()
    assert first == second
    decoded = json.loads(first.decode("utf-8"))
    assert decoded["format"] == "WANGSHENG_MEMORY_SNAPSHOT_V0.7"
    assert decoded["snapshot"]["occurrence_digest"] == kernel.occurrence_digest()


def test_p4_save_load_roundtrip_preserves_full_future_id_stream() -> None:
    fixture = _fixture()
    original, _ = MemoryVersioningKernel._build_xiaoman_day1_branch(  # noqa: SLF001
        fixture, "CAND_D1_NAME_SELF_REPORT"
    )
    restored = MemoryVersioningKernel.load_state(original.save_state())
    original_next = original.commit_event(
        world_tick=99,
        event_type="ROUNDTRIP_ID_CHECK",
        actor_ids=("actor.player",),
        target_ids=("object.front_door",),
        location_id="location.front_hall",
        payload={"ok": True},
    )
    restored_next = restored.commit_event(
        world_tick=99,
        event_type="ROUNDTRIP_ID_CHECK",
        actor_ids=("actor.player",),
        target_ids=("object.front_door",),
        location_id="location.front_hall",
        payload={"ok": True},
    )
    assert original_next.event_id == restored_next.event_id
    assert original_next.event_digest == restored_next.event_digest
    assert original.state_digest() == restored.state_digest()


def test_p4_snapshot_tampering_is_rejected_before_load() -> None:
    fixture = _fixture()
    kernel, _ = MemoryVersioningKernel._build_xiaoman_day1_branch(  # noqa: SLF001
        fixture, "CAND_D1_CRANE_CONNECTION"
    )
    decoded = json.loads(kernel.save_state().decode("utf-8"))
    decoded["snapshot"]["occurrence_cursor"] += 1
    tampered = json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(MemoryKernelError) as exc:
        MemoryVersioningKernel.load_state(tampered)
    assert exc.value.code == MemoryErrorCode.SAVE_DIGEST_MISMATCH


def test_p4_trace_replay_rejects_unknown_record_kind() -> None:
    kernel = MemoryVersioningKernel()
    kernel.commit_event(
        world_tick=1,
        event_type="KNOCK",
        actor_ids=("actor.xiaoman",),
        target_ids=("object.front_door",),
        location_id="location.front_hall",
        payload={"count": 3},
    )
    trace = [dict(item) for item in kernel._history_trace]  # noqa: SLF001
    trace[0] = {**trace[0], "kind": "UNKNOWN_KIND"}
    with pytest.raises(MemoryKernelError) as exc:
        MemoryVersioningKernel._from_history_trace(trace, config=kernel.config)  # noqa: SLF001
    assert exc.value.code == MemoryErrorCode.REPLAY_DIGEST_MISMATCH


def test_p4_all_day3_outcomes_preserve_identical_occurrence_history() -> None:
    fixture = _fixture()
    kernels = {
        outcome_id: MemoryVersioningKernel._build_xiaoman_day3_branch(fixture, outcome_id)[0]  # noqa: SLF001
        for outcome_id in fixture["day3_outcomes"]
    }
    digests = {item.occurrence_digest() for item in kernels.values()}
    assert len(digests) == 1
    event_types = {tuple(event.event_type for event in item.list_events()) for item in kernels.values()}
    assert len(event_types) == 1
    assert "ARCHIVE_DEATH_RECORD_READ" in next(iter(event_types))
    assert "BODY_CONTINUITY_INSPECTED" in next(iter(event_types))


def test_p4_new_person_outcome_cannot_inherit_old_kinship() -> None:
    fixture = _fixture()
    _, result = MemoryVersioningKernel._build_xiaoman_day3_branch(  # noqa: SLF001
        fixture, "NEW_PERSON_USING_NAME"
    )
    assert result.active_connection_claims[0].predicate == "CURRENT_PERSON_USES_NAME_XIAOMAN"
    assert "automatic_old_kinship" not in result.manifestation_state["inherited"]


def test_p4_refused_outcome_has_projection_but_no_connection_or_acknowledgement() -> None:
    fixture = _fixture()
    kernel, result = MemoryVersioningKernel._build_xiaoman_day3_branch(fixture, "REFUSED")  # noqa: SLF001
    assert result.active_connection_claims == ()
    assert not kernel._acknowledgements_by_id  # noqa: SLF001
    assert result.manifestation_state["manifestations"] == ("no_new_identity_connection",)
    assert kernel.replay_digest() == kernel.state_digest()


def test_p4_pending_record_roundtrip_preserves_ledger_but_not_authoritative_digest() -> None:
    fixture = _fixture()
    kernel, sources = MemoryVersioningKernel._build_xiaoman_day1_base(fixture)  # noqa: SLF001
    observation, memory = sources["CAND_D1_NAME_SELF_REPORT"]
    before = kernel.state_digest()
    record = kernel.create_name_record(
        NameRecordDraft(
            source_memory_version_ids=(memory.memory_version_id,),
            source_observation_ids=(observation.observation_id,),
            source_family_ids=(observation.source_family_id,),
            claim=memory.claim,
            permission_level=PermissionLevel.L1_WITNESS,
            confirmed_by_player=True,
            consenting_actor_ids=(),
            effective_from_tick=10,
            recognition_scope=RecognitionScope.HALL_LOCAL,
            mitigation_plan_ids=(),
            created_tick=10,
        )
    )
    assert kernel.state_digest() == before
    restored = MemoryVersioningKernel.load_state(kernel.save_state())
    assert restored.get_name_record(record.name_record_id) == record
    assert restored.state_digest() == before


def test_p4_manifestation_audit_window_evicts_old_deltas_without_losing_trace() -> None:
    fixture = _fixture()
    kernel, sources = MemoryVersioningKernel._build_xiaoman_day1_base(fixture)  # noqa: SLF001
    kernel.config = KernelConfig(manifestation_audit_window=2)
    kernel._manifestation_audit = __import__("collections").deque(maxlen=2)  # noqa: SLF001
    observation, memory = sources["CAND_D1_NAME_SELF_REPORT"]
    MemoryVersioningKernel._create_fixture_record(  # noqa: SLF001
        kernel,
        claim=memory.claim,
        permission=PermissionLevel.L1_WITNESS,
        observations=(observation,),
        memories=(memory,),
        effective_from_tick=10,
        created_tick=11,
        manifestation_changes={"a": 1, "b": 2, "c": 3},
        manifestation_rule_id="RULE_TEST_BOUND",
    )
    assert len(kernel._manifestation_audit) == 2  # noqa: SLF001
    trace = [
        item for item in kernel._history_trace
        if item["kind"] == "WORLD_ACKNOWLEDGEMENT_COMMITTED"
    ]  # noqa: SLF001
    assert len(trace[0]["payload"]["manifestation_deltas"]) == 3


def test_p4_branch_and_replay_result_value_objects_are_frozen() -> None:
    fixture = _fixture()
    _, result = MemoryVersioningKernel._build_xiaoman_day1_branch(  # noqa: SLF001
        fixture, "CAND_D1_QINGYAN_UNKNOWN"
    )
    with pytest.raises(FrozenInstanceError):
        result.branch_id = "changed"  # type: ignore[misc]


def test_p4_invalid_manifestation_plan_is_rejected_before_any_authoritative_mutation() -> None:
    fixture = _fixture()
    kernel, sources = MemoryVersioningKernel._build_xiaoman_day1_base(fixture)  # noqa: SLF001
    observation, memory = sources["CAND_D1_NAME_SELF_REPORT"]
    record = kernel.create_name_record(
        NameRecordDraft(
            source_memory_version_ids=(memory.memory_version_id,),
            source_observation_ids=(observation.observation_id,),
            source_family_ids=(observation.source_family_id,),
            claim=memory.claim,
            permission_level=PermissionLevel.L1_WITNESS,
            confirmed_by_player=True,
            consenting_actor_ids=(),
            effective_from_tick=10,
            recognition_scope=RecognitionScope.HALL_LOCAL,
            mitigation_plan_ids=(),
            created_tick=10,
        )
    )
    before_digest = kernel.state_digest()
    before_counters = dict(kernel._id_counters)  # noqa: SLF001
    before_trace_count = len(kernel._history_trace)  # noqa: SLF001
    with pytest.raises(MemoryKernelError) as exc:
        kernel.acknowledge_name_record(
            record.name_record_id,
            world_tick=20,
            manifestation_changes={"invalid.path": True},
            manifestation_rule_id="RULE_INVALID",
        )
    assert exc.value.code == MemoryErrorCode.ACK_PARTIAL_COMMIT_FORBIDDEN
    assert kernel.state_digest() == before_digest
    assert dict(kernel._id_counters) == before_counters  # noqa: SLF001
    assert len(kernel._history_trace) == before_trace_count  # noqa: SLF001
    assert kernel.active_connection_claims() == ()
