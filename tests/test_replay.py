from wangsheng.replay import replay_golden_trace


def test_golden_trace_replays_exactly():
    result = replay_golden_trace("golden_traces/normal_observe_and_report.json")
    assert result["passed"]
    assert result["records_match"]
    assert result["digest_match"]
