from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wangsheng.memory import (
    AccessState,
    KernelConfig,
    MemoryVersioningKernel,
    NameRecordDraft,
    PermissionLevel,
    RecognitionScope,
    SourceKind,
    VersionState,
)
from wangsheng.memory.kernel import _canonical_json
from .helpers import claim, observation_draft


def _source(kernel: MemoryVersioningKernel, *, alias: str = "小满"):
    source_claim = claim(object_value=alias, time_scope="P5_FORWARD")
    event = kernel.commit_event(
        world_tick=1,
        event_type="P5_SOURCE",
        actor_ids=("actor.xiaoman",),
        target_ids=("actor.player",),
        location_id="location.front_hall",
        payload={"alias": alias},
    )
    observation = kernel.record_observation(
        observation_draft(
            observer="actor.player",
            source_event_id=event.event_id,
            observed_claim=source_claim,
            source_family_id=f"FAMILY_P5_{alias}",
        ),
        visibility_claim=source_claim,
    )
    return source_claim, observation


def _new_memory(kernel: MemoryVersioningKernel, source_claim, observation, tick: int):
    return kernel.create_memory(
        owner_id="actor.player",
        observation_ids=(observation.observation_id,),
        claim=source_claim,
        source_kind=SourceKind.EXPERIENCED,
        initial_clarity_milli=900,
        initial_emotion_residue=(),
        created_tick=tick,
    )


def test_p5_versions_per_lineage_are_live_bounded_and_archived() -> None:
    kernel = MemoryVersioningKernel(KernelConfig(active_memory_versions_per_lineage=2))
    source_claim, observation = _source(kernel)
    current = _new_memory(kernel, source_claim, observation, 1)
    first_id = current.memory_version_id
    for tick in range(2, 6):
        current = kernel.rewrite_memory(
            memory_lineage_id=current.memory_lineage_id,
            parent_version_ids=(current.memory_version_id,),
            observation_ids=(observation.observation_id,),
            claim=source_claim,
            source_kind=SourceKind.EXPERIENCED,
            initial_clarity_milli=900,
            initial_emotion_residue=(),
            created_tick=tick,
            rewrite_reason_code="P5_BOUND_REWRITE",
        )
    assert len(kernel._lineage_versions[current.memory_lineage_id]) == 2  # noqa: SLF001
    assert first_id not in kernel._memory_versions  # noqa: SLF001
    assert kernel.get_memory_version(first_id).memory_version_id == first_id
    assert kernel.get_memory_state(first_id).version_state == VersionState.REWRITTEN
    assert any(
        item.object_kind == "MEMORY_VERSION" and item.object_id == first_id
        for item in kernel._recent_archive_references  # noqa: SLF001
    )


def test_p5_lineages_per_actor_are_live_bounded() -> None:
    kernel = MemoryVersioningKernel(KernelConfig(active_memory_lineages_per_actor=2))
    source_claim, observation = _source(kernel)
    created = [_new_memory(kernel, source_claim, observation, tick) for tick in range(1, 5)]
    assert len(kernel._actor_lineages["actor.player"]) == 2  # noqa: SLF001
    assert kernel._archived_memory_lineages == 2  # noqa: SLF001
    assert created[0].memory_lineage_id not in kernel._lineage_versions  # noqa: SLF001
    assert kernel.get_memory_version(created[0].memory_version_id) == created[0]


def test_p5_belief_query_cache_is_bounded_per_actor() -> None:
    kernel = MemoryVersioningKernel(KernelConfig(belief_query_cache_per_actor=2))
    source_claim, observation = _source(kernel)
    versions = [_new_memory(kernel, source_claim, observation, tick) for tick in range(1, 5)]
    for version in versions:
        assert kernel.query_memory(version.memory_version_id).access_state == AccessState.CLEAR
    assert len(kernel._belief_query_cache["actor.player"]) == 2  # noqa: SLF001


def test_p5_acknowledgement_and_inactive_connection_windows_are_bounded() -> None:
    config = KernelConfig(recent_acknowledgement_cache=2, manifestation_audit_window=2)
    kernel = MemoryVersioningKernel(config)
    sources = {}
    for alias in ("甲", "乙"):
        source_claim, observation = _source(kernel, alias=alias)
        sources[alias] = (source_claim, observation, _new_memory(kernel, source_claim, observation, 1))
    for index in range(6):
        alias = ("甲", "乙")[index % 2]
        source_claim, observation, memory = sources[alias]
        record = kernel.create_name_record(
            NameRecordDraft(
                source_memory_version_ids=(memory.memory_version_id,),
                source_observation_ids=(observation.observation_id,),
                source_family_ids=(observation.source_family_id,),
                claim=source_claim,
                permission_level=PermissionLevel.L1_WITNESS,
                confirmed_by_player=True,
                consenting_actor_ids=(),
                effective_from_tick=index + 2,
                recognition_scope=RecognitionScope.HALL_LOCAL,
                mitigation_plan_ids=("PLAN_PROSPECTIVE_REPLACEMENT",),
                created_tick=index + 2,
            )
        )
        kernel.acknowledge_name_record(
            record.name_record_id,
            world_tick=index + 2,
            manifestation_changes={"p5_alias": alias},
            manifestation_rule_id="RULE_P5_BOUND",
        )
    assert len(kernel._acknowledgements) == 2  # noqa: SLF001
    assert len(kernel._acknowledgements_by_id) == 2  # noqa: SLF001
    assert len(kernel._manifestation_audit) == 2  # noqa: SLF001
    assert len(kernel._connection_versions) <= 3  # active + two recent inactive  # noqa: SLF001
    assert len(kernel._active_connection_version_ids) == 1  # noqa: SLF001


def test_p5_save_load_after_multiple_evictions_is_exact() -> None:
    kernel = MemoryVersioningKernel(
        KernelConfig(
            active_memory_lineages_per_actor=4,
            active_memory_versions_per_lineage=2,
            recent_forgetting_events_cache=4,
            recent_acknowledgement_cache=4,
            belief_query_cache_per_actor=4,
            manifestation_audit_window=4,
        )
    )
    summary = kernel.run_same_world_stress(transitions=200, seed=7001)
    restored = MemoryVersioningKernel.load_state(kernel.save_state())
    assert summary.digest_mismatches == 0
    assert restored.state_digest() == kernel.state_digest()
    assert restored.save_state() == kernel.save_state()


def test_p5_same_world_stress_is_seed_deterministic() -> None:
    left = MemoryVersioningKernel()
    right = MemoryVersioningKernel()
    left_summary = left.run_same_world_stress(transitions=400, seed=7001)
    right_summary = right.run_same_world_stress(transitions=400, seed=7001)
    assert left_summary == right_summary
    assert left.state_digest() == right.state_digest()
    assert left.save_state() == right.save_state()


def test_p5_golden_trace_digest_and_replay_are_frozen() -> None:
    path = Path("golden_traces/v070_xiaoman_three_day.jsonl")
    expected_sha = Path("golden_traces/v070_xiaoman_three_day.sha256").read_text().split()[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [item["sequence"] for item in records] == list(range(1, len(records) + 1))
    replayed = MemoryVersioningKernel._from_history_trace(  # noqa: SLF001
        records, config=KernelConfig()
    )
    assert replayed.state_digest() == "f46dccab2257b789ea7ca05e11288348e6e33daf5f32d135ac30e039f7a516ee"
    assert replayed.occurrence_digest() == "13244a8b76a05e410d5c3d235394abf8c93c1c6a16f51a5c63e82b8884d31d1a"


def test_p5_golden_trace_regeneration_is_byte_identical() -> None:
    fixture = MemoryVersioningKernel._load_xiaoman_fixture(  # noqa: SLF001
        Path("specs/v0.7/scenarios/xiaoman_three_day_kernel_fixture_v0.7.json")
    )
    kernel, _ = MemoryVersioningKernel._build_xiaoman_day3_branch(  # noqa: SLF001
        fixture, "OLD_RESIDENT_CONTINUATION"
    )
    regenerated = "".join(_canonical_json(item) + "\n" for item in kernel._history_trace)  # noqa: SLF001
    assert regenerated.encode("utf-8") == Path(
        "golden_traces/v070_xiaoman_three_day.jsonl"
    ).read_bytes()
