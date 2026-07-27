from __future__ import annotations

from wangsheng.memory import AccessState, ForgettingMode, SourceKind, VersionState

from .helpers import claim, observation_draft, residue


def _memory_with_residue(kernel):
    event = kernel.commit_event(
        world_tick=1,
        event_type="DOOR_KNOCKED",
        actor_ids=("actor.xiaoman",),
        target_ids=("object.front_door",),
        location_id="location.front_hall",
        payload={"count": 3},
    )
    observed_claim = claim(subject="object.front_door", predicate="WAS_KNOCKED", object_value=3)
    observation = kernel.record_observation(
        observation_draft(
            observer="actor.qingyan",
            source_event_id=event.event_id,
            observed_claim=observed_claim,
        ),
        authorized_claim=observed_claim,
    )
    memory = kernel.create_memory(
        owner_id="actor.qingyan",
        observation_ids=(observation.observation_id,),
        claim=observed_claim,
        source_kind=SourceKind.EXPERIENCED,
        initial_clarity_milli=700,
        initial_emotion_residue=(residue(),),
        created_tick=1,
    )
    return event, observation, memory


def test_t06_fact_only_forgetting(kernel) -> None:
    _, _, memory = _memory_with_residue(kernel)
    state = kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.FACT_ONLY,
        reason_code="NIGHT_DECAY",
        decay_per_night_milli=450,
        explicit_penalty_milli=0,
        explicit_rehearsal_bonus_milli=0,
        world_tick=2,
    )
    result = kernel.query_memory(memory.memory_version_id)
    assert state.access_state == AccessState.FORGOTTEN
    assert result.claim is None
    assert len(result.emotion_residue) == 1
    assert result.emotion_residue[0].target_id == "object.front_door"


def test_t07_full_forgetting(kernel) -> None:
    event, _, memory = _memory_with_residue(kernel)
    state = kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.FACT_AND_EMOTION,
        reason_code="EXPLICIT_ERASURE",
        decay_per_night_milli=0,
        explicit_penalty_milli=1000,
        explicit_rehearsal_bonus_milli=0,
        world_tick=2,
    )
    result = kernel.query_memory(memory.memory_version_id)
    assert state.access_state == AccessState.FORGOTTEN
    assert result.claim is None
    assert result.emotion_residue == ()
    assert kernel.get_event(event.event_id).event_digest


def test_t08_rewrite_lineage(kernel) -> None:
    _, first_observation, memory_v1 = _memory_with_residue(kernel)
    manifested_claim = claim(
        subject="actor.qingyan",
        predicate="FEELS_FAMILIAR_WITH",
        object_value="actor.xiaoman",
        qualifiers={"derived": True},
    )
    memory_v2 = kernel.rewrite_memory(
        memory_lineage_id=memory_v1.memory_lineage_id,
        parent_version_ids=(memory_v1.memory_version_id,),
        observation_ids=(first_observation.observation_id,),
        claim=manifested_claim,
        source_kind=SourceKind.MANIFESTED,
        initial_clarity_milli=800,
        initial_emotion_residue=(),
        created_tick=3,
        rewrite_reason_code="WORLD_ACK_MANIFESTATION",
    )
    old_state = kernel.get_memory_state(memory_v1.memory_version_id)
    assert memory_v2.version_no == memory_v1.version_no + 1
    assert memory_v2.parent_version_ids == (memory_v1.memory_version_id,)
    assert old_state.version_state == VersionState.REWRITTEN
