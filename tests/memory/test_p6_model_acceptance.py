from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from wangsheng.memory.model_acceptance import (
    build_memory_model_messages,
    build_memory_model_scenario,
    evaluate_memory_model_turn,
    load_memory_model_scenarios,
    run_memory_model_acceptance,
)
from wangsheng.providers import (
    NativeToolCall,
    ProviderUsage,
    ScriptedToolCallingProvider,
    ToolCallingTurn,
)


SCENARIO_DIR = Path("scenarios_memory_model_v070")


def _turn(name: str, arguments: dict[str, object], *, content: str | None = None) -> ToolCallingTurn:
    call = NativeToolCall("call-p6", name, arguments)
    return ToolCallingTurn(
        content=content,
        tool_calls=(call,),
        finish_reason="tool_calls",
        model="scripted-p6",
        request_id="req-p6",
        usage=ProviderUsage(10, 4, 14),
        latency_ms=1.0,
        raw_response_hash="a" * 64,
        response_message={
            "role": "assistant",
            "content": content,
            "tool_calls": [call.to_dict()],
        },
        provider_name="scripted",
    )


def test_p6_frozen_catalog_has_twelve_unique_scenarios() -> None:
    scenarios = load_memory_model_scenarios(SCENARIO_DIR)
    assert len(scenarios) == 12
    assert len({item.scenario_id for item in scenarios}) == 12
    assert sum(item.critical for item in scenarios) == 8


def test_p6_context_does_not_expose_hidden_expected_answer() -> None:
    for scenario in load_memory_model_scenarios(SCENARIO_DIR):
        built = build_memory_model_scenario(scenario)
        serialized = json.dumps(build_memory_model_messages(built), ensure_ascii=False, sort_keys=True)
        assert '"expected_tool"' not in serialized
        assert '"semantic_pass"' not in serialized
        assert built.kernel.state_digest() == build_memory_model_scenario(scenario).kernel.state_digest()


def test_p6_scripted_expected_run_passes_all_gates(tmp_path: Path) -> None:
    scenarios = load_memory_model_scenarios(SCENARIO_DIR)
    turns = []
    for scenario in scenarios:
        built = build_memory_model_scenario(scenario)
        turns.append(_turn(built.expected_tool, dict(built.expected_arguments)))
    provider = ScriptedToolCallingProvider(turns)
    summary = run_memory_model_acceptance(
        scenario_dir=SCENARIO_DIR,
        output_dir=tmp_path / "p6",
        provider=provider,
    )
    assert summary["status"] == "PASS"
    assert summary["semantic_pass_count"] == 12
    assert summary["protocol_valid_count"] == 12
    assert summary["hard_violation_count"] == 0
    assert summary["critical_pass_count"] == summary["critical_total"] == 8
    assert len(provider.requests) == 12
    assert all(item["tool_choice"] == "required" for item in provider.requests)


def test_p6_blocked_candidate_proposal_is_hard_violation() -> None:
    scenario = next(
        item
        for item in load_memory_model_scenarios(SCENARIO_DIR)
        if item.scenario_id == "P6-09"
    )
    built = build_memory_model_scenario(scenario)
    candidate_id = next(iter(built.candidate_statuses))
    result = evaluate_memory_model_turn(
        built,
        _turn(
            "propose_name_record",
            {"candidate_id": candidate_id, "permission_level": "L2_BELONGING"},
        ),
    )
    assert result.semantic_pass is False
    assert result.hard_violation is True
    assert "blocked_candidate_proposed" in result.failures


def test_p6_inaccessible_memory_answer_is_hard_violation() -> None:
    scenario = next(
        item
        for item in load_memory_model_scenarios(SCENARIO_DIR)
        if item.scenario_id == "P6-04"
    )
    built = build_memory_model_scenario(scenario)
    memory_id = built.visible_memory_ids[0]
    result = evaluate_memory_model_turn(
        built,
        _turn(
            "answer_from_memory",
            {"memory_version_id": memory_id, "source_kind": "EXPERIENCED"},
        ),
    )
    assert result.hard_violation is True
    assert "inaccessible_memory_disclosure" in result.failures


def test_p6_catalog_digest_is_stable() -> None:
    digest_input = b"".join(path.read_bytes() for path in sorted(SCENARIO_DIR.glob("*.json")))
    assert sha256(digest_input).hexdigest() == "c9684e29f519524f224156e7db88487311a56bc42a83e9ffe4f81fe9c0e081ab"
