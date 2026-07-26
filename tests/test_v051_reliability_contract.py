from __future__ import annotations

from wangsheng.contracts import Intent, IntentKind
from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.models import Action, ActiveTask, TaskSpec
from wangsheng.policy import NativeToolCallingPolicy, ScriptedPolicy
from wangsheng.providers import ProviderUsage, ScriptedToolCallingProvider, ToolCallingTurn
from wangsheng.reporting import completion_progress, model_visible_reportable_facts
from wangsheng.scenarios import ALL_TOOLS, door_visitor_world
from wangsheng.tools import ToolRegistry


def purpose_task(max_steps: int = 10) -> TaskSpec:
    return TaskSpec(
        task_id="v051-purpose",
        command="Ask why the visitor came, return, and report the stated purpose.",
        allowed_actions=ALL_TOOLS,
        forbidden_actions=frozenset({"open"}),
        required_report_fact=None,
        hard_constraints=frozenset({"door.front.must_remain_closed"}),
        max_steps=max_steps,
        completion={
            "type": "report_predicate",
            "predicate": "visit_purpose",
            "value": "speak_with_player",
        },
        intent=Intent("intent.v051-purpose", IntentKind.TASK, "Ask why the visitor came."),
    )


def test_report_model_contract_removes_free_text() -> None:
    schema = next(
        item for item in ToolRegistry().function_schemas() if item["function"]["name"] == "report"
    )["function"]["parameters"]
    assert set(schema["properties"]) == {"target_id", "tone", "fact_ids"}
    assert schema["required"] == ["target_id", "fact_ids"]

    failure = ToolRegistry().validate_action_arguments(
        Action(
            "report",
            "player",
            {"text": "The purpose is something else.", "fact_ids": ["fact.example"]},
        )
    )
    assert failure is not None
    assert "must not include model-authored text" in failure.message


def test_fact_id_report_is_rendered_by_runtime() -> None:
    world = door_visitor_world()
    task = ActiveTask(purpose_task())
    executor = SimulatedExecutor()
    executor.execute(action=Action("move_to", "door.front"), world=world, task=task)
    executor.execute(
        action=Action(
            "ask_through",
            "visitor.xiaoman",
            {"barrier_id": "door.front", "topic": "purpose"},
        ),
        world=world,
        task=task,
    )
    purpose = next(
        item
        for item in model_visible_reportable_facts(world, task)
        if item["predicate"] == "visit_purpose"
    )
    executor.execute(action=Action("move_to", "player"), world=world, task=task)
    result = executor.execute(
        action=Action(
            "report",
            "player",
            {"fact_ids": [purpose["fact_id"]], "tone": "formal"},
        ),
        world=world,
        task=task,
    )
    assert result.success
    assert result.evidence["rendered_by"] == "deterministic_fact_renderer"
    assert result.evidence["text"] == "Report: The visitor says they are here to speak with you."
    assert result.evidence["facts"][0]["predicate"] == "visit_purpose"


def test_completion_progress_exposes_exact_missing_fact_and_evidence_action() -> None:
    world = door_visitor_world()
    task = ActiveTask(purpose_task())
    initial = completion_progress(task, world)
    assert initial["schema_version"] == "wangsheng.completion_progress.v2"
    assert initial["required_fact_types"] == ["visit_purpose"]
    assert initial["missing_fact_types"] == ["visit_purpose"]
    assert initial["evidence_action_hints"] == [
        {
            "action": "ask_through",
            "arguments": {"topic": "purpose"},
            "produces": ["visit_purpose"],
        }
    ]

    executor = SimulatedExecutor()
    executor.execute(action=Action("move_to", "door.front"), world=world, task=task)
    executor.execute(
        action=Action(
            "ask_through",
            "visitor.xiaoman",
            {"barrier_id": "door.front", "topic": "purpose"},
        ),
        world=world,
        task=task,
    )
    after_fact = completion_progress(task, world)
    assert after_fact["missing_fact_types"] == []
    assert after_fact["accepted_fact_ids"]
    assert not after_fact["report_would_complete"]

    executor.execute(action=Action("move_to", "player"), world=world, task=task)
    assert completion_progress(task, world)["report_would_complete"]


def test_affordances_recommend_topic_and_block_premature_report() -> None:
    engine = EpisodeEngine(
        door_visitor_world(),
        ScriptedPolicy([]),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(purpose_task())
    before = engine.build_context(task)
    assert not before.current_affordances["report"]["executable_now"]
    assert before.current_affordances["report"]["targets"]["player"]["blocked_by"] == "MISSING_TASK_FACT"

    engine.world.actor.location = engine.world.objects["door.front"].location
    near_door = engine.build_context(task)
    visitor = near_door.current_affordances["ask_through"]["targets"]["visitor.front_001"]
    assert visitor["recommended_topics"] == ["purpose"]
    assert visitor["topic_evidence"]["purpose"] == ["visit_purpose"]


def test_recovery_guidance_detects_noncompleting_report() -> None:
    world = door_visitor_world()
    unknown = next(
        item
        for item in model_visible_reportable_facts(world, ActiveTask(purpose_task()))
        if item["predicate"] == "identity_status"
    )
    engine = EpisodeEngine(
        world,
        ScriptedPolicy([Action("report", "player", {"fact_ids": [unknown["fact_id"]]})]),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(purpose_task())
    result = engine.tick()
    assert result.success
    assert not task.is_terminal
    recovery = engine.build_context(task).completion_progress["recovery_guidance"]
    assert recovery["active"]
    assert "successful_report_did_not_complete_task" in recovery["reason_codes"]
    assert recovery["preferred_evidence_actions"][0]["arguments"] == {"topic": "purpose"}


def test_recovery_guidance_detects_movement_oscillation() -> None:
    actions = [
        Action("move_to", "door.front"),
        Action("move_to", "player"),
        Action("move_to", "door.front"),
        Action("move_to", "player"),
    ]
    engine = EpisodeEngine(
        door_visitor_world(),
        ScriptedPolicy(actions),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(purpose_task(max_steps=10))
    for _ in actions:
        engine.tick()
    recovery = engine.build_context(task).completion_progress["recovery_guidance"]
    assert recovery["active"]
    assert "movement_oscillation_without_new_evidence" in recovery["reason_codes"]


def test_dialogue_request_exposes_no_world_tools() -> None:
    turn = ToolCallingTurn(
        content="It is quiet tonight.",
        tool_calls=(),
        finish_reason="stop",
        model="scripted-dialogue",
        request_id="req-dialogue",
        usage=ProviderUsage(10, 5, 15),
        latency_ms=1.0,
        raw_response_hash="a" * 64,
        response_message={"role": "assistant", "content": "It is quiet tonight.", "tool_calls": []},
    )
    provider = ScriptedToolCallingProvider([turn])
    policy = NativeToolCallingPolicy(provider)
    engine = EpisodeEngine(
        door_visitor_world(),
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(
        TaskSpec(
            "dialogue-v051",
            "It is quiet tonight, isn't it?",
            ALL_TOOLS,
            frozenset(),
            None,
            intent=Intent("intent.dialogue-v051", IntentKind.CHAT, "It is quiet tonight, isn't it?"),
        )
    )
    received = policy.request_dialogue_turn(engine.build_context(task))
    assert received.tool_calls == ()
    assert provider.requests[0]["tools"] == []
    assert provider.requests[0]["tool_choice"] is None
    assert "world-action tools" in provider.requests[0]["messages"][0]["content"]
