from __future__ import annotations

import pytest

from wangsheng.memory import (
    AccessState,
    ForgettingMode,
    MemoryErrorCode,
    MemoryKernelError,
    ObservationDraft,
    SourceKind,
)

from .helpers import claim, observation_draft, residue


def _event(kernel, payload=None):
    return kernel.commit_event(
        world_tick=1,
        event_type="TEST_EVENT",
        actor_ids=("actor.xiaoman",),
        target_ids=("object.front_door",),
        location_id="location.front_hall",
        payload=payload or {"visible": True},
    )


def _memory(kernel, *, clarity=700, residues=()):
    event = _event(kernel)
    observed_claim = claim(predicate="SAW", object_value="object.front_door")
    observation = kernel.record_observation(
        observation_draft(
            observer="actor.player",
            source_event_id=event.event_id,
            observed_claim=observed_claim,
        ),
        visibility_claim=observed_claim,
    )
    memory = kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(observation.observation_id,),
        claim=observed_claim,
        source_kind=SourceKind.EXPERIENCED,
        initial_clarity_milli=clarity,
        initial_emotion_residue=residues,
        created_tick=1,
    )
    return event, observation, memory


def test_p2_nested_event_payload_is_detached(kernel) -> None:
    payload = {"nested": {"items": [1, {"value": 2}]}}
    event = _event(kernel, payload)
    payload["nested"]["items"][1]["value"] = 99
    assert event.payload["nested"]["items"][1]["value"] == 2
    with pytest.raises(TypeError):
        event.payload["nested"]["new"] = True


def test_p2_occurrence_ids_and_digest_are_deterministic() -> None:
    from wangsheng.memory import MemoryVersioningKernel

    left = MemoryVersioningKernel()
    right = MemoryVersioningKernel()
    left_event = _event(left, {"b": 2, "a": 1})
    right_event = _event(right, {"a": 1, "b": 2})
    assert left_event.event_id == right_event.event_id
    assert left_event.event_digest == right_event.event_digest
    assert left.occurrence_digest() == right.occurrence_digest()


def test_p2_visibility_envelope_rejects_hidden_qualifier(kernel) -> None:
    event = _event(kernel)
    visible = claim(qualifiers={"holder": "UNKNOWN"})
    leaked = claim(qualifiers={"holder": "actor.xiaoman"})
    with pytest.raises(MemoryKernelError) as exc:
        kernel.record_observation(
            observation_draft(
                observer="actor.qingyan",
                source_event_id=event.event_id,
                observed_claim=leaked,
            ),
            visibility_claim=visible,
        )
    assert exc.value.code == MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK
    assert exc.value.args == (exc.value.message,)


def test_p2_heard_observation_requires_speaker(kernel) -> None:
    event = _event(kernel)
    observed_claim = claim()
    draft = observation_draft(
        observer="actor.player",
        source_event_id=event.event_id,
        observed_claim=observed_claim,
        source_kind=SourceKind.HEARD,
        source_actor_id=None,
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.record_observation(draft, visibility_claim=observed_claim)
    assert exc.value.code == MemoryErrorCode.MEMORY_UNKNOWN_SOURCE


def test_p2_inferred_observation_requires_rule_or_multiple_sources(kernel) -> None:
    event = _event(kernel)
    observed_claim = claim()
    draft = observation_draft(
        observer="actor.player",
        source_event_id=event.event_id,
        observed_claim=observed_claim,
        source_kind=SourceKind.INFERRED,
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.record_observation(draft, visibility_claim=observed_claim)
    assert exc.value.code == MemoryErrorCode.MEMORY_UNKNOWN_SOURCE

    allowed = ObservationDraft(
        **{
            field: getattr(draft, field)
            for field in draft.__dataclass_fields__
            if field != "inference_rule_id"
        },
        inference_rule_id="RULE_VISIBLE_SHAPE",
    )
    assert kernel.record_observation(allowed, visibility_claim=observed_claim).inference_rule_id


def test_p2_manifested_observation_requires_acknowledgement_provenance(kernel) -> None:
    event = _event(kernel)
    observed_claim = claim()
    draft = observation_draft(
        observer="actor.player",
        source_event_id=event.event_id,
        observed_claim=observed_claim,
        source_kind=SourceKind.MANIFESTED,
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.record_observation(draft, visibility_claim=observed_claim)
    assert exc.value.code == MemoryErrorCode.MEMORY_UNKNOWN_SOURCE


def test_p2_memory_owner_cannot_consume_private_observation(kernel) -> None:
    event = _event(kernel)
    observed_claim = claim()
    observation = kernel.record_observation(
        observation_draft(
            observer="actor.qingyan",
            source_event_id=event.event_id,
            observed_claim=observed_claim,
        ),
        visibility_claim=observed_claim,
    )
    with pytest.raises(MemoryKernelError) as exc:
        kernel.create_memory(
            owner_id="actor.player",
            observation_ids=(observation.observation_id,),
            claim=observed_claim,
            source_kind=SourceKind.EXPERIENCED,
            initial_clarity_milli=900,
            initial_emotion_residue=(),
            created_tick=1,
        )
    assert exc.value.code == MemoryErrorCode.MEMORY_KNOWLEDGE_LEAK


def test_p2_suppress_and_unsuppress_preserve_fact_and_residue(kernel) -> None:
    _, _, memory = _memory(kernel, residues=(residue(),))
    suppressed = kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.SUPPRESS,
        reason_code="STORY_SEAL",
        decay_per_night_milli=0,
        explicit_penalty_milli=0,
        explicit_rehearsal_bonus_milli=0,
        world_tick=2,
    )
    assert suppressed.access_state == AccessState.SUPPRESSED
    assert kernel.query_memory(memory.memory_version_id).claim is None
    restored = kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.UNSUPPRESS,
        reason_code="STORY_UNSEAL",
        decay_per_night_milli=0,
        explicit_penalty_milli=0,
        explicit_rehearsal_bonus_milli=0,
        world_tick=3,
    )
    assert restored.access_state == AccessState.CLEAR
    assert kernel.query_memory(memory.memory_version_id).claim == memory.claim


def test_p2_fact_only_drops_access_dependent_residue_when_forgotten(kernel) -> None:
    dependent = residue()
    dependent = type(dependent)(
        emotion_type=dependent.emotion_type,
        intensity_milli=dependent.intensity_milli,
        target_id=dependent.target_id,
        origin_memory_version_id=None,
        decay_per_night_milli=dependent.decay_per_night_milli,
        access_independent=False,
    )
    _, _, memory = _memory(kernel, clarity=300, residues=(dependent,))
    kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.FACT_ONLY,
        reason_code="NIGHT_DECAY",
        decay_per_night_milli=1,
        explicit_penalty_milli=0,
        explicit_rehearsal_bonus_milli=0,
        world_tick=2,
    )
    assert kernel.query_memory(memory.memory_version_id).emotion_residue == ()


def test_p2_untrusted_manifested_rewrite_is_rejected_atomically(kernel) -> None:
    _, observation, memory = _memory(kernel)
    before_state = kernel.get_memory_state(memory.memory_version_id)
    with pytest.raises(MemoryKernelError) as exc:
        kernel.rewrite_memory(
            memory_lineage_id=memory.memory_lineage_id,
            parent_version_ids=(memory.memory_version_id,),
            observation_ids=(observation.observation_id,),
            claim=claim(predicate="FEELS_FAMILIAR_WITH", object_value="actor.xiaoman"),
            source_kind=SourceKind.MANIFESTED,
            initial_clarity_milli=800,
            initial_emotion_residue=(),
            created_tick=3,
            rewrite_reason_code="UNTRUSTED_SCRIPT",
        )
    assert exc.value.code == MemoryErrorCode.MEMORY_INVALID_TRANSITION
    assert kernel.get_memory_state(memory.memory_version_id) == before_state


def test_p2_decay_does_not_implicitly_unsuppress(kernel) -> None:
    _, _, memory = _memory(kernel, clarity=700)
    kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.SUPPRESS,
        reason_code="STORY_SEAL",
        decay_per_night_milli=0,
        explicit_penalty_milli=0,
        explicit_rehearsal_bonus_milli=0,
        world_tick=2,
    )
    decayed = kernel.transition_memory(
        memory.memory_version_id,
        mode=ForgettingMode.FACT_ONLY,
        reason_code="NIGHT_DECAY",
        decay_per_night_milli=500,
        explicit_penalty_milli=0,
        explicit_rehearsal_bonus_milli=0,
        world_tick=3,
    )
    assert decayed.access_state == AccessState.SUPPRESSED
    assert decayed.clarity_milli == 200
