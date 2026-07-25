import json

from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.policy import ScriptedPolicy
from wangsheng.scenarios import door_visitor_task, door_visitor_world, reference_door_actions
from wangsheng.trace import JsonlTraceRecorder, state_delta


def test_state_delta_reports_nested_changes():
    delta = state_delta({"door": {"open": False}}, {"door": {"open": True}})
    assert delta == {"door.open": {"from": False, "to": True}}


def test_jsonl_trace_has_layered_results(tmp_path):
    recorder = JsonlTraceRecorder(tmp_path / "trace.jsonl", "episode-test")
    engine = EpisodeEngine(door_visitor_world(), ScriptedPolicy(reference_door_actions()), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator(), trace_recorder=recorder)
    task = engine.submit_command(door_visitor_task()); engine.run_until_terminal()
    assert not recorder.validate()
    lines = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 5
    assert lines[0]["gateway"]["status"] == "allowed"
    assert lines[0]["executor"]["status"] == "success"
    assert lines[-1]["task_status"] == "succeeded"
    assert lines[-1]["action"]["action_id"].endswith("a005")
