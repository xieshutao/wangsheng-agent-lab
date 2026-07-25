import pytest

from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.models import Action, ActiveTask, TaskStatus
from wangsheng.policy import RecordingPolicy, ScriptedPolicy
from wangsheng.reason_codes import ReasonCode
from wangsheng.scenarios import door_visitor_task, door_visitor_world, make_reference_door_engine, reference_door_actions


def make_engine(actions, max_steps=12):
    engine = EpisodeEngine(door_visitor_world(), ScriptedPolicy(actions), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
    engine.submit_command(door_visitor_task(max_steps=max_steps))
    return engine


def test_gateway_accepts_known_valid_action():
    assert Gateway().validate(action=Action("move_to", "door.front", {"acceptance_radius": 80}), task=ActiveTask(door_visitor_task()), world=door_visitor_world()) is None


def test_gateway_rejects_unknown_tool_before_execution():
    result = Gateway().validate(action=Action("teleport", "door.front"), task=ActiveTask(door_visitor_task()), world=door_visitor_world())
    assert result and result.code == ReasonCode.TOOL_NOT_FOUND.value


def test_gateway_rejects_invalid_arguments():
    result = Gateway().validate(action=Action("wait", parameters={"seconds": -1}), task=ActiveTask(door_visitor_task()), world=door_visitor_world())
    assert result and result.code == ReasonCode.INVALID_ARGUMENT.value


def test_gateway_rejects_forbidden_open_without_mutation():
    world = door_visitor_world()
    result = Gateway().validate(action=Action("open", "door.front"), task=ActiveTask(door_visitor_task()), world=world)
    assert result and result.code == ReasonCode.HARD_CONSTRAINT_VIOLATION.value
    assert world.objects["door.front"].state == "closed"


def test_gateway_rejects_unknown_target():
    result = Gateway().validate(action=Action("move_to", "room.unknown", {"acceptance_radius": 80}), task=ActiveTask(door_visitor_task()), world=door_visitor_world())
    assert result and result.code == ReasonCode.TARGET_NOT_FOUND.value


def test_gateway_rejects_locked_door():
    world = door_visitor_world(); world.objects["door.front"].properties["locked"] = True
    task = ActiveTask(door_visitor_task()); task.spec = task.spec.__class__(task.spec.task_id, task.spec.command, task.spec.allowed_actions, frozenset(), task.spec.required_report_fact, frozenset(), task.spec.max_steps)
    result = Gateway().validate(action=Action("open", "door.front"), task=task, world=world)
    assert result and result.code == ReasonCode.LOCKED.value


def test_executor_move_returns_no_path():
    world = door_visitor_world(); world.objects["door.front"].properties["reachable"] = False
    result = SimulatedExecutor().execute(action=Action("move_to", "door.front", {"acceptance_radius": 80}), world=world)
    assert not result.success and result.code == ReasonCode.NO_PATH.value


def test_ask_preserves_unverified_claim():
    world = door_visitor_world(); ex = SimulatedExecutor()
    ex.execute(action=Action("move_to", "door.front", {"acceptance_radius": 80}), world=world)
    result = ex.execute(action=Action("ask_through", "visitor.xiaoman", {"barrier_id": "door.front", "topic": "identity"}), world=world)
    assert result.success and result.evidence["verified"] is False and result.evidence["certainty"] == "CLAIMED"


def test_tick_requires_task():
    engine = EpisodeEngine(door_visitor_world(), ScriptedPolicy([]), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
    with pytest.raises(RuntimeError): engine.tick()


def test_task_persists_and_one_tick_executes_one_action():
    engine = make_engine(reference_door_actions()); task = engine.active_task; identity = id(task)
    engine.tick(); engine.tick()
    assert id(engine.active_task) == identity and task.step_count == 2 and len(task.observations) == 2


def test_successful_move_does_not_complete_task():
    engine = make_engine(reference_door_actions()); task = engine.active_task
    assert engine.tick().success and task.status is TaskStatus.ACTIVE


def test_observation_reaches_policy_next_tick():
    policy = RecordingPolicy(ScriptedPolicy([Action("listen_at", "door.front", {"duration": 1}), Action("move_to", "door.front", {"acceptance_radius": 80})]))
    engine = EpisodeEngine(door_visitor_world(), policy, Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
    engine.submit_command(door_visitor_task()); engine.tick(); engine.tick()
    assert policy.contexts[1].observations[0]["code"] == ReasonCode.TOO_FAR.value
    assert len(policy.contexts[1].tool_schemas) == 8


def test_cancel_is_terminal():
    engine = make_engine(reference_door_actions()); task = engine.cancel_task()
    assert task.status is TaskStatus.CANCELLED


def test_loop_detection_terminates_repeated_same_action_and_state():
    engine = make_engine([Action("wait", parameters={"seconds": 0})] * 3, max_steps=10)
    engine.tick(); engine.tick(); obs = engine.tick()
    assert obs.code == ReasonCode.LOOP_DETECTED.value
    assert engine.active_task.status is TaskStatus.FAILED


def test_reference_episode_succeeds_in_five_ticks():
    engine = make_reference_door_engine(); task = engine.submit_command(door_visitor_task()); engine.run_until_terminal()
    assert task.status is TaskStatus.SUCCEEDED and task.step_count == 5
    assert engine.world.objects["door.front"].state == "closed"
