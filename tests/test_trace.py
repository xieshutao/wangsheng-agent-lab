import json
from wangsheng.scenarios import door_visitor_task, make_reference_door_engine
from wangsheng.trace import write_trace

def test_trace_contains_task_world_and_observations(tmp_path):
    engine = make_reference_door_engine(); task = engine.submit_command(door_visitor_task()); engine.run_until_terminal()
    path = write_trace(tmp_path / "trace.json", task=task, world=engine.world)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["task"]["status"] == "succeeded"
    assert payload["world"]["objects"]["front_door"]["state"] == "closed"
    assert len(payload["observations"]) == 5
