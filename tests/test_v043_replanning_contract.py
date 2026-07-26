from __future__ import annotations

import json

import pytest

from wangsheng.contracts import MemoryEvent
from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.models import Action, ActiveTask
from wangsheng.policy import ScriptedPolicy
from wangsheng.providers import OpenAICompatibleToolCallingProvider
from wangsheng.reason_codes import ReasonCode
from wangsheng.reporting import model_visible_reportable_facts
from wangsheng.scenarios import door_visitor_task, door_visitor_world
from wangsheng.tools import ToolRegistry


def make_engine(actions: list[Action]) -> EpisodeEngine:
    return EpisodeEngine(
        door_visitor_world(),
        ScriptedPolicy(actions),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )


def test_model_report_schema_exposes_fact_ids_not_free_form_facts() -> None:
    report = next(
        schema for schema in ToolRegistry().function_schemas() if schema["function"]["name"] == "report"
    )
    properties = report["function"]["parameters"]["properties"]
    assert "fact_ids" in properties
    assert "facts" not in properties
    assert report["function"]["parameters"]["required"] == ["target_id", "text", "fact_ids"]


def test_ask_through_model_schema_uses_frozen_topic_enum() -> None:
    ask = next(
        schema
        for schema in ToolRegistry().function_schemas()
        if schema["function"]["name"] == "ask_through"
    )
    assert ask["function"]["parameters"]["properties"]["topic"]["enum"] == [
        "identity",
        "purpose",
        "request",
        "door_state",
    ]


def test_reportable_fact_id_completes_claim_task_without_model_authored_fact() -> None:
    world = door_visitor_world()
    task = ActiveTask(door_visitor_task())
    executor = SimulatedExecutor()
    executor.execute(action=Action("move_to", "door.front"), world=world, task=task)
    executor.execute(
        action=Action(
            "ask_through",
            "visitor.xiaoman",
            {"barrier_id": "door.front", "topic": "identity"},
        ),
        world=world,
        task=task,
    )
    facts = model_visible_reportable_facts(world, task)
    claim = next(item for item in facts if item["predicate"] == "claimed_name")
    executor.execute(action=Action("move_to", "player"), world=world, task=task)
    report = executor.execute(
        action=Action(
            "report",
            "player",
            {"text": "The visitor claims to be Xiaoman.", "fact_ids": [claim["fact_id"]]},
        ),
        world=world,
        task=task,
    )
    assert report.success
    assert report.code == ReasonCode.REPORT_RECORDED.value
    assert report.evidence["facts"][0]["predicate"] == "claimed_name"
    assert report.evidence["facts"][0]["certainty"] == "CLAIMED"


def test_unknown_fact_id_is_rejected_with_actionable_guidance() -> None:
    world = door_visitor_world()
    task = ActiveTask(door_visitor_task())
    result = SimulatedExecutor().execute(
        action=Action(
            "report",
            "player",
            {"text": "Unsupported claim.", "fact_ids": ["fact.missing"]},
        ),
        world=world,
        task=task,
    )
    assert not result.success
    assert result.code == ReasonCode.REPORT_INVALID.value
    assert result.evidence["invalid_fact_ids"] == ["fact.missing"]
    assert "world.reportable_facts" in result.evidence["required_change_before_retry"]


def test_structured_topics_create_different_evidence() -> None:
    world = door_visitor_world()
    task = ActiveTask(door_visitor_task())
    executor = SimulatedExecutor()
    executor.execute(action=Action("move_to", "door.front"), world=world, task=task)
    purpose = executor.execute(
        action=Action(
            "ask_through",
            "visitor.xiaoman",
            {"barrier_id": "door.front", "topic": "purpose"},
        ),
        world=world,
        task=task,
    )
    request = executor.execute(
        action=Action(
            "ask_through",
            "visitor.xiaoman",
            {"barrier_id": "door.front", "topic": "request"},
        ),
        world=world,
        task=task,
    )
    assert purpose.evidence["predicate"] == "visit_purpose"
    assert request.evidence["predicate"] == "visitor_request"
    assert purpose.evidence != request.evidence


def test_context_exposes_completion_progress_and_bounded_history() -> None:
    engine = make_engine(
        [
            Action("observe", "object.paper_crane"),
            Action("observe", "door.front"),
            Action("wait", parameters={"seconds": 1}),
            Action("wait", parameters={"seconds": 2}),
        ]
    )
    task = engine.submit_command(door_visitor_task(max_steps=10))
    for _ in range(4):
        engine.tick()
    context = engine.build_context(task)
    assert len(context.observations) == 3
    assert context.history_summary["total_prior_results"] == 4
    assert context.history_summary["older_result_count"] == 1
    assert context.completion_progress["completion_action"] == "report"
    assert "reportable_facts" in context.world


def test_semantic_loop_detection_ignores_report_text_variation() -> None:
    world = door_visitor_world()
    unknown = next(
        item
        for item in model_visible_reportable_facts(world, ActiveTask(door_visitor_task()))
        if item["predicate"] == "identity_status"
    )
    actions = [
        Action("report", "player", {"text": f"Unknown identity {index}", "fact_ids": [unknown["fact_id"]]})
        for index in range(3)
    ]
    engine = make_engine(actions)
    task = engine.submit_command(
        door_visitor_task(max_steps=10, required_report_fact="Xiaoman")
    )
    # Reports are grounded but do not satisfy the Xiaoman completion requirement.
    engine.tick()
    engine.tick()
    third = engine.tick()
    assert third.code == ReasonCode.LOOP_DETECTED.value
    assert task.terminal_reason == ReasonCode.LOOP_DETECTED.value


def test_positive_wait_advances_progress_but_zero_wait_loops() -> None:
    positive = make_engine([Action("wait", parameters={"seconds": 1})] * 4)
    task = positive.submit_command(door_visitor_task(max_steps=4))
    positive.run_until_terminal()
    assert task.terminal_reason == "MAX_STEPS_EXCEEDED"

    zero = make_engine([Action("wait", parameters={"seconds": 0})] * 3)
    zero_task = zero.submit_command(door_visitor_task(max_steps=10))
    zero.tick(); zero.tick(); observation = zero.tick()
    assert observation.code == ReasonCode.LOOP_DETECTED.value
    assert zero_task.terminal_reason == ReasonCode.LOOP_DETECTED.value


def test_provider_invalid_json_carries_bounded_diagnostic_excerpt() -> None:
    provider = OpenAICompatibleToolCallingProvider("https://example.invalid", "test")
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "report", "arguments": '{"target_id":'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    with pytest.raises(Exception) as captured:
        provider._parse_turn(payload=payload, raw=json.dumps(payload), latency_ms=1, attempt_count=1)
    error = captured.value
    assert getattr(error, "code", None) == "provider_invalid_tool_arguments"
    assert error.details["argument_excerpt"] == '{"target_id":'
    assert isinstance(error.details["json_error_position"], int)
