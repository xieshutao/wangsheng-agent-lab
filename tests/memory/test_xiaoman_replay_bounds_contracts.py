from __future__ import annotations

from wangsheng.memory import MemoryVersioningKernel


def test_t17_day1_branch_matrix(xiaoman_fixture_path) -> None:
    branches = MemoryVersioningKernel.run_xiaoman_day1_branches(xiaoman_fixture_path)
    assert set(branches) == {
        "CAND_D1_NAME_SELF_REPORT",
        "CAND_D1_CRANE_CONNECTION",
        "CAND_D1_QINGYAN_UNKNOWN",
        "CAND_D1_NONE",
    }
    assert len({result.occurrence_digest for result in branches.values()}) == 1
    assert branches["CAND_D1_NAME_SELF_REPORT"].manifestation_state["xiaoman_presence_delta"] == 1
    assert branches["CAND_D1_CRANE_CONNECTION"].manifestation_state["crane_stable"] is True
    assert branches["CAND_D1_QINGYAN_UNKNOWN"].manifestation_state["qingyan_explicit_unknown"] is True
    assert branches["CAND_D1_NONE"].manifestation_state["all_unrecorded_memories_decay"] is True


def test_t18_day3_outcome_matrix(xiaoman_fixture_path) -> None:
    outcomes = MemoryVersioningKernel.run_xiaoman_day3_outcomes(xiaoman_fixture_path)
    assert set(outcomes) == {
        "OLD_RESIDENT_CONTINUATION",
        "NEW_PERSON_USING_NAME",
        "NAME_ONLY_HISTORY_UNRESOLVED",
        "REFUSED",
    }
    assert len({result.state_digest for result in outcomes.values()}) == 4
    assert len({result.occurrence_digest for result in outcomes.values()}) == 1
    assert outcomes["REFUSED"].active_connection_claims == ()
    assert "qingyan_manifested_familiarity" in outcomes["OLD_RESIDENT_CONTINUATION"].manifestation_state["manifestations"]
    assert "automatic_old_kinship" not in outcomes["NEW_PERSON_USING_NAME"].manifestation_state.get("inherited", ())


def test_t19_save_load_replay(xiaoman_fixture_path) -> None:
    verification = MemoryVersioningKernel.verify_xiaoman_save_load_replay(xiaoman_fixture_path)
    assert verification.checkpoints >= 3
    assert verification.state_match is True
    assert verification.snapshot_digest == verification.replay_digest
    assert len(verification.branch_digests) >= 4


def test_t20_same_world_bounds_stress(kernel) -> None:
    summary = kernel.run_same_world_stress(transitions=10_000, seed=7001)
    assert summary.transitions == 10_000
    assert summary.max_active_lineages_per_actor <= kernel.config.active_memory_lineages_per_actor
    assert summary.max_active_versions_per_lineage <= kernel.config.active_memory_versions_per_lineage
    assert summary.max_recent_forgetting_events <= kernel.config.recent_forgetting_events_cache
    assert summary.max_recent_acknowledgements <= kernel.config.recent_acknowledgement_cache
    assert summary.max_belief_query_cache_per_actor <= kernel.config.belief_query_cache_per_actor
    assert summary.max_manifestation_audit_window <= kernel.config.manifestation_audit_window
    assert summary.lineage_cycles == 0
    assert summary.partial_commits == 0
    assert summary.digest_mismatches == 0
    assert summary.history_trace_records >= 10_000
