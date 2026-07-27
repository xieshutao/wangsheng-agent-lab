from __future__ import annotations

import pytest

from wangsheng.memory import (
    MemoryErrorCode,
    MemoryKernelError,
    Polarity,
    SourceKind,
    UNKNOWN,
    VersionState,
)

from .helpers import claim, observation_draft, residue


def test_t01_occurrence_append_only(kernel) -> None:
    mutable_payload = {"count": 3}
    event = kernel.commit_event(
        world_tick=1,
        event_type="DOOR_KNOCKED",
        actor_ids=("actor.xiaoman",),
        target_ids=("object.front_door",),
        location_id="location.front_hall",
        payload=mutable_payload,
    )
    digest_before = event.event_digest
    mutable_payload["count"] = 99
    assert event.payload["count"] == 3
    assert event.event_digest == digest_before

    with pytest.raises(MemoryKernelError) as update_error:
        kernel.replace_event(event.event_id, payload={"count": 4})
    assert update_error.value.code == MemoryErrorCode.OCCURRENCE_MUTATION_FORBIDDEN

    with pytest.raises(MemoryKernelError) as delete_error:
        kernel.delete_event(event.event_id)
    assert delete_error.value.code == MemoryErrorCode.OCCURRENCE_MUTATION_FORBIDDEN
    assert kernel.get_event(event.event_id).event_digest == digest_before


def test_t02_observation_isolation(kernel) -> None:
    event = kernel.commit_event(
        world_tick=1,
        event_type="OBJECT_TRANSFERRED",
        actor_ids=("actor.xiaoman",),
        target_ids=("object.paper_crane",),
        location_id="location.front_hall",
        payload={"through": "door_gap", "hidden_holder": "actor.xiaoman"},
    )
    authorized = claim(
        subject="object.paper_crane",
        predicate="TRANSFERRED_THROUGH",
        object_value="door_gap",
        qualifiers={"holder": UNKNOWN},
    )
    observed = kernel.record_observation(
        observation_draft(
            observer="actor.qingyan",
            source_event_id=event.event_id,
            observed_claim=authorized,
            source_family_id="FAMILY_CRANE_PHYSICAL",
        ),
        visibility_claim=authorized,
    )
    assert observed.claim.qualifiers["holder"] == UNKNOWN
    assert "actor.xiaoman" not in repr(observed.claim.qualifiers)


def test_t03_heard_provenance(kernel) -> None:
    speech = kernel.commit_event(
        world_tick=2,
        event_type="SPEECH",
        actor_ids=("actor.xiaoman",),
        target_ids=("actor.player",),
        location_id="location.front_hall",
        payload={"utterance": "I call myself Xiaoman"},
    )
    self_name_claim = claim()
    observed = kernel.record_observation(
        observation_draft(
            observer="actor.player",
            source_event_id=speech.event_id,
            observed_claim=self_name_claim,
            source_kind=SourceKind.HEARD,
            source_actor_id="actor.xiaoman",
            source_family_id="FAMILY_SELF_REPORT",
        ),
        visibility_claim=self_name_claim,
    )
    assert observed.source_kind == SourceKind.HEARD
    assert observed.source_actor_id == "actor.xiaoman"
    assert kernel.get_event(speech.event_id).event_type == "SPEECH"
    assert all(event.event_type != "IDENTITY_CANONICALLY_ESTABLISHED" for event in kernel.list_events())


def test_t04_multi_version_memory(kernel) -> None:
    event = kernel.commit_event(
        world_tick=3,
        event_type="OBJECT_TRANSFERRED",
        actor_ids=("actor.xiaoman",),
        target_ids=("object.paper_crane",),
        location_id="location.front_hall",
        payload={"through": "door_gap"},
    )
    player_claim = claim(subject="object.paper_crane", predicate="APPEARED_IN", object_value="location.front_hall")
    qingyan_claim = claim(subject="object.paper_crane", predicate="CAME_THROUGH", object_value="object.front_door")
    player_obs = kernel.record_observation(
        observation_draft(observer="actor.player", source_event_id=event.event_id, observed_claim=player_claim),
        visibility_claim=player_claim,
    )
    qingyan_obs = kernel.record_observation(
        observation_draft(observer="actor.qingyan", source_event_id=event.event_id, observed_claim=qingyan_claim),
        visibility_claim=qingyan_claim,
    )
    player_memory = kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(player_obs.observation_id,),
        claim=player_claim,
        source_kind=SourceKind.EXPERIENCED,
        initial_clarity_milli=900,
        initial_emotion_residue=(),
        created_tick=3,
    )
    qingyan_memory = kernel.create_memory(
        owner_id="actor.qingyan",
        observation_ids=(qingyan_obs.observation_id,),
        claim=qingyan_claim,
        source_kind=SourceKind.EXPERIENCED,
        initial_clarity_milli=900,
        initial_emotion_residue=(),
        created_tick=3,
    )
    assert player_memory.claim != qingyan_memory.claim
    assert player_obs.source_event_ids == qingyan_obs.source_event_ids == (event.event_id,)


def test_t05_knowledge_leak_rejection(kernel) -> None:
    event = kernel.commit_event(
        world_tick=4,
        event_type="DOOR_OCCLUDED_PERSON_PRESENT",
        actor_ids=("actor.xiaoman",),
        target_ids=("object.front_door",),
        location_id="location.front_hall",
        payload={"hidden_body_identity": "old_resident.xiaoman"},
    )
    authorized = claim(
        predicate="BODY_IDENTITY",
        object_value=UNKNOWN,
        polarity=Polarity.UNKNOWN,
    )
    leaked = claim(predicate="BODY_IDENTITY", object_value="old_resident.xiaoman")
    with pytest.raises(MemoryKernelError) as exc:
        kernel.record_observation(
            observation_draft(
                observer="actor.qingyan",
                source_event_id=event.event_id,
                observed_claim=leaked,
            ),
            visibility_claim=authorized,
        )
    assert exc.value.code == MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK
