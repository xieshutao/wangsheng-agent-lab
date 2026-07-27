from __future__ import annotations

from wangsheng.memory import (
    Claim,
    EmotionalResidue,
    ObservationDraft,
    Polarity,
    RecognitionScope,
    SourceKind,
)


def claim(
    *,
    subject: str = "actor.xiaoman",
    predicate: str = "SELF_IDENTIFIED_AS",
    object_value: object = "小满",
    time_scope: str = "D1_CURRENT",
    scope: RecognitionScope = RecognitionScope.HALL_LOCAL,
    polarity: Polarity = Polarity.AFFIRM,
    qualifiers: dict[str, object] | None = None,
) -> Claim:
    return Claim(
        subject_id=subject,
        predicate=predicate,
        object_id_or_value=object_value,
        time_scope=time_scope,
        recognition_scope=scope,
        polarity=polarity,
        qualifiers=qualifiers or {},
    )


def observation_draft(
    *,
    observer: str,
    source_event_id: str,
    observed_claim: Claim,
    source_kind: SourceKind = SourceKind.EXPERIENCED,
    source_actor_id: str | None = None,
    source_family_id: str = "FAMILY_DAY1",
    derived_from_acknowledgement_id: str | None = None,
    inference_rule_id: str | None = None,
) -> ObservationDraft:
    return ObservationDraft(
        observer_id=observer,
        source_kind=source_kind,
        source_event_ids=(source_event_id,),
        source_observation_ids=(),
        source_actor_id=source_actor_id,
        source_evidence_id=None,
        source_family_id=source_family_id,
        claim=observed_claim,
        confidence_milli=900,
        acquired_tick=1,
        world_version_seen=1,
        derived_from_acknowledgement_id=derived_from_acknowledgement_id,
        inference_rule_id=inference_rule_id,
    )


def residue(*, intensity: int = 800, target: str = "object.front_door") -> EmotionalResidue:
    return EmotionalResidue(
        emotion_type="UNEASE",
        intensity_milli=intensity,
        target_id=target,
        origin_memory_version_id=None,
        decay_per_night_milli=50,
        access_independent=True,
    )
