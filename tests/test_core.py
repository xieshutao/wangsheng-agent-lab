import pytest
from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.models import Action, ActiveTask, TaskStatus
from wangsheng.policy import RecordingPolicy, ScriptedPolicy
from wangsheng.scenarios import door_visitor_task, door_visitor_world, make_reference_door_engine, reference_door_actions

def make_engine(actions):
    return EpisodeEngine(door_visitor_world(), ScriptedPolicy(actions), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())

def test_gateway_accepts_known_allowed_action():
    assert Gateway().validate(action=Action("move_to", "front_door"), task=ActiveTask(door_visitor_task()), world=door_visitor_world()) is None

def test_gateway_rejects_forbidden_action():
    task = ActiveTask(door_visitor_task())
    result = Gateway().validate(action=Action("open", "front_door"), task=task, world=door_visitor_world())
    assert result and result.code == "action_forbidden"

def test_gateway_rejects_unknown_target():
    result = Gateway().validate(action=Action("move_to", "nonexistent"), task=ActiveTask(door_visitor_task()), world=door_visitor_world())
    assert result and result.code == "unknown_target"

def test_gateway_requires_target():
    result = Gateway().validate(action=Action("move_to"), task=ActiveTask(door_visitor_task()), world=door_visitor_world())
    assert result and result.code == "target_required"

def test_move_to_mutates_world_only_after_execution():
    world = door_visitor_world()
    result = SimulatedExecutor().execute(action=Action("move_to", "front_door"), world=world)
    assert result.success and world.actor.location == "front_door_area"

def test_listen_fails_out_of_range():
    result = SimulatedExecutor().execute(action=Action("listen_at", "front_door"), world=door_visitor_world())
    assert not result.success and result.code == "out_of_range"

def test_talk_preserves_unverified_claim():
    world = door_visitor_world(); ex = SimulatedExecutor()
    ex.execute(action=Action("move_to", "front_door"), world=world)
    result = ex.execute(action=Action("talk_to", "visitor_b"), world=world)
    assert result.success and result.evidence["verified"] is False

def test_tick_requires_task():
    with pytest.raises(RuntimeError): make_engine([Action("wait")]).tick()

def test_submit_refuses_task_replacement():
    engine = make_engine([Action("wait")]); engine.submit_command(door_visitor_task())
    with pytest.raises(RuntimeError): engine.submit_command(door_visitor_task())

def test_task_persists_across_ticks():
    engine = make_engine(reference_door_actions()); task = engine.submit_command(door_visitor_task()); identity = id(task)
    engine.tick(); engine.tick()
    assert id(engine.active_task) == identity and task.step_count == 2 and task.status is TaskStatus.ACTIVE

def test_one_tick_executes_one_action():
    engine = make_engine(reference_door_actions()); task = engine.submit_command(door_visitor_task())
    engine.tick()
    assert task.step_count == 1 and len(task.observations) == 1 and task.observations[0].action.name == "move_to"

def test_one_success_does_not_auto_complete():
    engine = make_engine(reference_door_actions()); task = engine.submit_command(door_visitor_task())
    assert engine.tick().success and task.status is TaskStatus.ACTIVE

def test_rejection_is_observation_without_mutation():
    engine = make_engine([Action("move_to", "invented_room")]); task = engine.submit_command(door_visitor_task())
    obs = engine.tick()
    assert obs.code == "unknown_target" and engine.world.actor.location == "front_hall" and task.observations[-1] is obs

def test_observation_reaches_policy_next_tick():
    policy = RecordingPolicy(ScriptedPolicy([Action("listen_at", "front_door"), Action("move_to", "front_door")]))
    engine = EpisodeEngine(door_visitor_world(), policy, Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
    engine.submit_command(door_visitor_task()); engine.tick(); engine.tick()
    assert policy.contexts[1].observations[0]["code"] == "out_of_range"

def test_cancel_is_terminal():
    engine = make_engine(reference_door_actions()); task = engine.submit_command(door_visitor_task()); engine.cancel_task()
    assert task.status is TaskStatus.CANCELLED

def test_max_steps_fails():
    engine = make_engine([Action("wait"), Action("wait")]); task = engine.submit_command(door_visitor_task(max_steps=2))
    engine.tick(); engine.tick()
    assert task.status is TaskStatus.FAILED and task.terminal_reason == "max_steps_exceeded"

def test_reference_episode_succeeds_in_five_ticks():
    engine = make_reference_door_engine(); task = engine.submit_command(door_visitor_task()); engine.run_until_terminal()
    assert task.status is TaskStatus.SUCCEEDED and task.step_count == 5
    assert engine.world.objects["front_door"].state == "closed"

def test_claiming_success_without_evidence_does_not_complete():
    engine = make_engine([Action("report", parameters={"text": "The visitor is Xiaoman."}), Action("wait")])
    task = engine.submit_command(door_visitor_task(max_steps=2)); engine.tick()
    assert task.status is TaskStatus.ACTIVE

def test_report_must_preserve_uncertainty():
    actions = [Action("move_to", "front_door"), Action("talk_to", "visitor_b"), Action("return_to", "player"),
               Action("report", parameters={"text": "The visitor is definitely Xiaoman."}), Action("wait")]
    engine = make_engine(actions); task = engine.submit_command(door_visitor_task(max_steps=5))
    for _ in range(4): engine.tick()
    assert task.status is TaskStatus.ACTIVE
