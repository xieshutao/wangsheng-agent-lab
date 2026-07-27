from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from wangsheng.memory import (
    AcknowledgementOutcome,
    MemoryErrorCode,
    MemoryKernelError,
    NameRecordDraft,
    PermissionLevel,
    RecognitionScope,
    RecordStatus,
    SourceKind,
)

from .helpers import claim, observation_draft


def _source(kernel, *, actor: str = "actor.xiaoman", family: str = "FAMILY_SELF_REPORT"):
    event = kernel.commit_event(
        world_tick=1,
        event_type="SPEECH",
        actor_ids=(actor,),
        target_ids=("actor.player",),
        location_id="location.front_hall",
        payload={"utterance": f"I am {actor}"},
    )
    source_claim = claim(subject=actor)
    observation = kernel.record_observation(
        observation_draft(
            observer="actor.player",
            source_event_id=event.event_id,
            observed_claim=source_claim,
            source_kind=SourceKind.HEARD,
            source_actor_id=actor,
            source_family_id=family,
        ),
        visibility_claim=source_claim,
    )
    memory = kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(observation.observation_id,),
        claim=source_claim,
        source_kind=SourceKind.HEARD,
        initial_clarity_milli=800,
        initial_emotion_residue=(),
        created_tick=1,
    )
    return observation, memory


def _draft(
    memory,
    observation,
    *,
    record_claim=None,
    permission=PermissionLevel.L1_WITNESS,
    consent=(),
    mitigation=(),
    confirmed=True,
    scope=RecognitionScope.HALL_LOCAL,
):
    record_claim = record_claim or memory.claim
    return NameRecordDraft(
        source_memory_version_ids=(memory.memory_version_id,),
        source_observation_ids=(observation.observation_id,),
        source_family_ids=(observation.source_family_id,),
        claim=record_claim,
        permission_level=permission,
        confirmed_by_player=confirmed,
        consenting_actor_ids=tuple(consent),
        effective_from_tick=2,
        recognition_scope=scope,
        mitigation_plan_ids=tuple(mitigation),
        created_tick=2,
    )


def test_p3_record_is_immutable_and_independent_of_draft_containers(kernel) -> None:
    observation, memory = _source(kernel)
    consent = ["actor.xiaoman"]
    mitigation = ["PLAN_PROSPECTIVE_REPLACEMENT"]
    record = kernel.create_name_record(
        _draft(memory, observation, consent=consent, mitigation=mitigation)
    )
    consent.append("actor.qingyan")
    mitigation.clear()
    assert record.consenting_actor_ids == ("actor.xiaoman",)
    assert record.mitigation_plan_ids == ("PLAN_PROSPECTIVE_REPLACEMENT",)
    with pytest.raises(FrozenInstanceError):
        record.record_status = RecordStatus.REJECTED  # type: ignore[misc]


def test_p3_l2_belonging_requires_subject_consent(kernel) -> None:
    observation, memory = _source(kernel)
    visitor = claim(
        predicate="PROTECTED_VISITOR_OF",
        object_value="institution.wangsheng_hall",
        time_scope="FROM_D2_FORWARD",
        qualifiers={"temporary": True},
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.create_name_record(
            _draft(
                memory,
                observation,
                record_claim=visitor,
                permission=PermissionLevel.L2_BELONGING,
                consent=(),
            )
        )
    assert exc.value.code == MemoryErrorCode.RECORD_CONSENT_REQUIRED


def test_p3_public_recognition_is_out_of_scope(kernel) -> None:
    observation, memory = _source(kernel)
    public_claim = claim(scope=RecognitionScope.PUBLIC)
    with pytest.raises(MemoryKernelError) as exc:
        kernel.create_name_record(
            _draft(
                memory,
                observation,
                record_claim=public_claim,
                scope=RecognitionScope.PUBLIC,
            )
        )
    assert exc.value.code == MemoryErrorCode.RECORD_PERMISSION_EXCEEDED


def test_p3_thematic_similarity_does_not_create_world_conflict(kernel) -> None:
    observation, memory = _source(kernel)
    first = claim(
        subject="actor.xiaoman",
        predicate="PROTECTED_VISITOR_OF",
        object_value="institution.wangsheng_hall",
        time_scope="FROM_D2_FORWARD",
    )
    first_record = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=first,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.xiaoman",),
        )
    )
    kernel.acknowledge_name_record(first_record.name_record_id, world_tick=2)

    second = claim(
        subject="actor.qingyan",
        predicate="PROTECTED_VISITOR_OF",
        object_value="institution.wangsheng_hall",
        time_scope="FROM_D2_FORWARD",
    )
    second_record = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=second,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.qingyan",),
        )
    )
    acknowledgement = kernel.acknowledge_name_record(second_record.name_record_id, world_tick=2)
    assert acknowledgement.conflict_ids == ()
    assert kernel.active_connection_claims() == (first, second)


def test_p3_logical_exclusion_can_only_replace_prospectively(kernel) -> None:
    observation, memory = _source(kernel)
    first_record = kernel.create_name_record(_draft(memory, observation))
    first_ack = kernel.acknowledge_name_record(first_record.name_record_id, world_tick=2)

    replacement_claim = claim(object_value="小曼")
    replacement_record = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=replacement_claim,
            mitigation=("PLAN_PROSPECTIVE_REPLACEMENT",),
        )
    )
    replacement_ack = kernel.acknowledge_name_record(replacement_record.name_record_id, world_tick=3)
    assert first_ack.outcome == AcknowledgementOutcome.ESTABLISHED
    assert replacement_ack.outcome == AcknowledgementOutcome.PROSPECTIVELY_REPLACED
    assert len(replacement_ack.superseded_connection_version_ids) == 1
    assert kernel.active_connection_claims() == (replacement_claim,)


def test_p3_institutional_exclusivity_requires_typed_mitigation(kernel) -> None:
    observation, memory = _source(kernel)
    first_claim = claim(
        subject="actor.qingyan",
        predicate="SOLE_OFFICE_HOLDER_OF",
        object_value="office.front_hall_keeper",
    )
    first = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=first_claim,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.qingyan",),
        )
    )
    kernel.acknowledge_name_record(first.name_record_id, world_tick=2)
    second_claim = claim(
        subject="actor.xiaoman",
        predicate="SOLE_OFFICE_HOLDER_OF",
        object_value="office.front_hall_keeper",
    )
    second = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=second_claim,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.xiaoman",),
        )
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.acknowledge_name_record(second.name_record_id, world_tick=3)
    assert exc.value.code == MemoryErrorCode.CONFLICT_MITIGATION_REQUIRED
    assert exc.value.details["conflict_type"] == "INSTITUTIONAL_EXCLUSIVITY"


def test_p3_declared_capacity_competition_counts_all_active_claimants(kernel) -> None:
    observation, memory = _source(kernel)
    for actor in ("actor.xiaoman", "actor.qingyan"):
        capacity_claim = claim(
            subject=actor,
            predicate="CLAIMS_CAPACITY_SLOT_IN",
            object_value="room.front_hall_beds",
            qualifiers={"resource_key": "front_hall_beds", "declared_capacity": 2},
        )
        record = kernel.create_name_record(
            _draft(
                memory,
                observation,
                record_claim=capacity_claim,
                permission=PermissionLevel.L2_BELONGING,
                consent=(actor,),
            )
        )
        kernel.acknowledge_name_record(record.name_record_id, world_tick=2)

    third_claim = claim(
        subject="actor.player",
        predicate="CLAIMS_CAPACITY_SLOT_IN",
        object_value="room.front_hall_beds",
        qualifiers={"resource_key": "front_hall_beds", "declared_capacity": 2},
    )
    third = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=third_claim,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.player",),
        )
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.acknowledge_name_record(third.name_record_id, world_tick=3)
    assert exc.value.code == MemoryErrorCode.CONFLICT_MITIGATION_REQUIRED
    assert exc.value.details["conflict_type"] == "DECLARED_CAPACITY_COMPETITION"


def test_p3_failed_acknowledgement_does_not_consume_ack_id(kernel) -> None:
    observation, memory = _source(kernel)
    first_claim = claim(
        subject="actor.qingyan",
        predicate="EXCLUSIVE_OCCUPANT_OF",
        object_value="slot.front_hall",
    )
    first = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=first_claim,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.qingyan",),
        )
    )
    assert kernel.acknowledge_name_record(first.name_record_id, world_tick=2).acknowledgement_id.endswith("00000001")

    conflicting = claim(
        subject="actor.xiaoman",
        predicate="EXCLUSIVE_OCCUPANT_OF",
        object_value="slot.front_hall",
    )
    rejected = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=conflicting,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.xiaoman",),
        )
    )
    with pytest.raises(MemoryKernelError):
        kernel.acknowledge_name_record(rejected.name_record_id, world_tick=3)

    unrelated = claim(
        subject="actor.xiaoman",
        predicate="PROTECTED_VISITOR_OF",
        object_value="institution.wangsheng_hall",
        time_scope="FROM_D3_FORWARD",
    )
    accepted = kernel.create_name_record(
        _draft(
            memory,
            observation,
            record_claim=unrelated,
            permission=PermissionLevel.L2_BELONGING,
            consent=("actor.xiaoman",),
        )
    )
    ack = kernel.acknowledge_name_record(accepted.name_record_id, world_tick=3)
    assert ack.acknowledgement_id.endswith("00000002")


def test_p3_nonexclusive_memories_cannot_be_marked_contradicted(kernel) -> None:
    observation, memory_v1 = _source(kernel)
    memory_v2 = kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(observation.observation_id,),
        claim=claim(predicate="HAS_OLD_CONNECTION_TO", object_value="institution.wangsheng_hall"),
        source_kind=SourceKind.INFERRED,
        initial_clarity_milli=600,
        initial_emotion_residue=(),
        created_tick=2,
        memory_lineage_id=memory_v1.memory_lineage_id,
        parent_version_ids=(memory_v1.memory_version_id,),
        rewrite_reason_code="ADDITIONAL_INTERPRETATION",
    )
    before = kernel.state_digest()
    with pytest.raises(MemoryKernelError) as exc:
        kernel.register_contradiction(
            (memory_v1.memory_version_id, memory_v2.memory_version_id),
            detected_tick=3,
        )
    assert exc.value.code == MemoryErrorCode.CONFLICT_UNSUPPORTED_TYPE
    assert kernel.state_digest() == before


def test_p3_unconfirmed_draft_cannot_be_acknowledged(kernel) -> None:
    observation, memory = _source(kernel)
    record = kernel.create_name_record(
        _draft(memory, observation, confirmed=False)
    )
    assert record.record_status == RecordStatus.DRAFT
    with pytest.raises(MemoryKernelError) as exc:
        kernel.acknowledge_name_record(record.name_record_id, world_tick=2)
    assert exc.value.code == MemoryErrorCode.RECORD_SCHEMA_INCOMPLETE
