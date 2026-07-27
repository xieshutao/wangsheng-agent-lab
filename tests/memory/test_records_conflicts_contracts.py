from __future__ import annotations

import pytest

from wangsheng.memory import (
    AcknowledgementOutcome,
    AccessState,
    ForgettingMode,
    MemoryErrorCode,
    MemoryKernelError,
    NameRecordDraft,
    PermissionLevel,
    RecognitionScope,
    RecordStatus,
    SourceKind,
    VersionState,
)

from .helpers import claim, observation_draft


def _source_memory(kernel, *, source_family: str = "FAMILY_SELF_REPORT"):
    event = kernel.commit_event(
        world_tick=1,
        event_type="SPEECH",
        actor_ids=("actor.xiaoman",),
        target_ids=("actor.player",),
        location_id="location.front_hall",
        payload={"utterance": "I call myself Xiaoman"},
    )
    observed_claim = claim()
    observation = kernel.record_observation(
        observation_draft(
            observer="actor.player",
            source_event_id=event.event_id,
            observed_claim=observed_claim,
            source_kind=SourceKind.HEARD,
            source_actor_id="actor.xiaoman",
            source_family_id=source_family,
        ),
        authorized_claim=observed_claim,
    )
    memory = kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(observation.observation_id,),
        claim=observed_claim,
        source_kind=SourceKind.HEARD,
        initial_clarity_milli=700,
        initial_emotion_residue=(),
        created_tick=1,
    )
    return event, observation, memory


def _draft(memory, observation, *, permission=PermissionLevel.L1_WITNESS, record_claim=None, families=None, consent=(), mitigation=(), parent_acks=()):
    return NameRecordDraft(
        source_memory_version_ids=(memory.memory_version_id,),
        source_observation_ids=(observation.observation_id,),
        source_family_ids=tuple(families or (observation.source_family_id,)),
        claim=record_claim or memory.claim,
        permission_level=permission,
        confirmed_by_player=True,
        consenting_actor_ids=tuple(consent),
        effective_from_tick=2,
        recognition_scope=RecognitionScope.HALL_LOCAL,
        mitigation_plan_ids=tuple(mitigation),
        created_tick=2,
        parent_acknowledgement_ids=tuple(parent_acks),
    )


def test_t09_record_memory_independence(kernel) -> None:
    _, observation, memory = _source_memory(kernel)
    record = kernel.create_name_record(_draft(memory, observation))
    kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.FACT_ONLY,
        reason_code="NIGHT_DECAY",
        decay_per_night_milli=500,
        explicit_penalty_milli=0,
        explicit_rehearsal_bonus_milli=0,
        world_tick=3,
    )
    assert kernel.query_memory(memory.memory_version_id).access_state == AccessState.FORGOTTEN
    assert kernel.get_name_record(record.name_record_id).record_status == RecordStatus.CONFIRMED


def test_t10_contradiction_preservation(kernel) -> None:
    _, observation, memory_v1 = _source_memory(kernel)
    opposite_claim = claim(predicate="SELF_IDENTIFIED_AS", object_value="NOT_XIAOMAN")
    memory_v2 = kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(observation.observation_id,),
        claim=opposite_claim,
        source_kind=SourceKind.INFERRED,
        initial_clarity_milli=600,
        initial_emotion_residue=(),
        created_tick=2,
        memory_lineage_id=memory_v1.memory_lineage_id,
        parent_version_ids=(memory_v1.memory_version_id,),
        rewrite_reason_code="CONTRARY_EVIDENCE",
    )
    states = kernel.register_contradiction(
        (memory_v1.memory_version_id, memory_v2.memory_version_id),
        detected_tick=3,
    )
    assert {state.version_state for state in states} == {VersionState.CONTRADICTED}
    assert kernel.query_memory(memory_v1.memory_version_id).memory_version_id == memory_v1.memory_version_id
    assert kernel.query_memory(memory_v2.memory_version_id).memory_version_id == memory_v2.memory_version_id


def test_t11_source_family_dedupe(kernel) -> None:
    _, observation, memory = _source_memory(kernel, source_family="FAMILY_CRANE_PHYSICAL")
    with pytest.raises(MemoryKernelError) as exc:
        kernel.create_name_record(
            _draft(
                memory,
                observation,
                families=("FAMILY_CRANE_PHYSICAL", "FAMILY_CRANE_PHYSICAL"),
            )
        )
    assert exc.value.code == MemoryErrorCode.EVIDENCE_SOURCE_FAMILY_DUPLICATE


def test_t12_anti_self_proof(kernel) -> None:
    event = kernel.commit_event(
        world_tick=4,
        event_type="MANIFESTATION_APPLIED",
        actor_ids=(),
        target_ids=("location.front_hall",),
        location_id="location.front_hall",
        payload={"derived_from_acknowledgement_id": "ACK_PARENT"},
    )
    manifested_claim = claim(predicate="CONTINUES_OLD_RESIDENT_CONNECTION", object_value="institution.wangsheng_hall")
    observation = kernel.record_observation(
        observation_draft(
            observer="actor.player",
            source_event_id=event.event_id,
            observed_claim=manifested_claim,
            source_kind=SourceKind.MANIFESTED,
            source_family_id="FAMILY_DERIVED_ACK_PARENT",
            derived_from_acknowledgement_id="ACK_PARENT",
        ),
        authorized_claim=manifested_claim,
    )
    memory = kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(observation.observation_id,),
        claim=manifested_claim,
        source_kind=SourceKind.MANIFESTED,
        initial_clarity_milli=1000,
        initial_emotion_residue=(),
        created_tick=4,
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.create_name_record(
            _draft(
                memory,
                observation,
                permission=PermissionLevel.L3_LIMITED_CONTINUITY,
                consent=("actor.xiaoman",),
                parent_acks=("ACK_PARENT",),
            )
        )
    assert exc.value.code == MemoryErrorCode.EVIDENCE_SELF_PROVING


def test_t13_l1_permission_boundary(kernel) -> None:
    _, observation, memory = _source_memory(kernel)
    permanent_claim = claim(predicate="PERMANENT_RESIDENT_OF", object_value="institution.wangsheng_hall", time_scope="ALWAYS")
    with pytest.raises(MemoryKernelError) as exc:
        kernel.create_name_record(
            _draft(memory, observation, permission=PermissionLevel.L1_WITNESS, record_claim=permanent_claim)
        )
    assert exc.value.code == MemoryErrorCode.RECORD_PERMISSION_EXCEEDED


def test_t14_l2_temporary_visitor(kernel) -> None:
    _, observation, memory = _source_memory(kernel)
    occurrence_before = kernel.occurrence_digest()
    visitor_claim = claim(
        predicate="PROTECTED_VISITOR_OF",
        object_value="institution.wangsheng_hall",
        time_scope="FROM_D2_FORWARD",
        qualifiers={"temporary": True},
    )
    record = kernel.create_name_record(
        _draft(
            memory,
            observation,
            permission=PermissionLevel.L2_BELONGING,
            record_claim=visitor_claim,
            consent=("actor.xiaoman",),
        )
    )
    acknowledgement = kernel.acknowledge_name_record(
        record.name_record_id,
        outcome=AcknowledgementOutcome.ESTABLISHED,
        world_tick=2,
    )
    assert acknowledgement.outcome == AcknowledgementOutcome.ESTABLISHED
    assert visitor_claim in kernel.active_connection_claims()
    assert kernel.occurrence_digest() == occurrence_before


def test_t15_l3_consent_and_evidence(kernel) -> None:
    _, observation, memory = _source_memory(kernel)
    old_resident_claim = claim(
        predicate="CONTINUES_OLD_RESIDENT_CONNECTION",
        object_value="institution.wangsheng_hall",
        time_scope="FROM_D3_FORWARD",
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.create_name_record(
            _draft(
                memory,
                observation,
                permission=PermissionLevel.L3_LIMITED_CONTINUITY,
                record_claim=old_resident_claim,
                consent=(),
            )
        )
    assert exc.value.code == MemoryErrorCode.RECORD_CONSENT_REQUIRED


def test_t16_typed_conflict_requires_mitigation(kernel) -> None:
    _, observation, memory = _source_memory(kernel)
    first_claim = claim(subject="actor.qingyan", predicate="EXCLUSIVE_OCCUPANT_OF", object_value="slot.front_hall")
    first_record = kernel.create_name_record(
        _draft(
            memory,
            observation,
            permission=PermissionLevel.L2_BELONGING,
            record_claim=first_claim,
            consent=("actor.qingyan",),
            mitigation=("PLAN_KEEP_EXISTING",),
        )
    )
    kernel.acknowledge_name_record(first_record.name_record_id, outcome=AcknowledgementOutcome.ESTABLISHED, world_tick=2)
    before = kernel.state_digest()
    competing_claim = claim(subject="actor.xiaoman", predicate="EXCLUSIVE_OCCUPANT_OF", object_value="slot.front_hall")
    second_record = kernel.create_name_record(
        _draft(
            memory,
            observation,
            permission=PermissionLevel.L2_BELONGING,
            record_claim=competing_claim,
            consent=("actor.xiaoman",),
            mitigation=(),
        )
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.acknowledge_name_record(second_record.name_record_id, outcome=AcknowledgementOutcome.ESTABLISHED, world_tick=3)
    assert exc.value.code == MemoryErrorCode.CONFLICT_MITIGATION_REQUIRED
    assert kernel.state_digest() == before
