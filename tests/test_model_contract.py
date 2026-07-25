from __future__ import annotations

import json
from urllib import request
import pytest

from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.models import PolicyContext, TaskStatus
from wangsheng.parser import StrictActionParser
from wangsheng.policy import ModelPolicy
from wangsheng.prompting import ActionPromptBuilder
from wangsheng.providers import OpenAICompatibleProvider, ScriptedTextProvider
from wangsheng.scenarios import claimed_fact, door_visitor_task, door_visitor_world


def context():
    return PolicyContext("Do not open the door.", "test", 1, ("listen_at", "move_to"), ("open",), {"door": {"state": "closed"}}, ({"code": "TOO_FAR", "success": False},), Gateway().registry.function_schemas(frozenset({"listen_at", "move_to"})))


def test_parser_accepts_exact_action_object():
    action = StrictActionParser().parse('{"name":"move_to","target":"door.front","parameters":{"acceptance_radius":80}}')
    assert action.name == "move_to" and action.target == "door.front"


@pytest.mark.parametrize(("raw", "code"), [
    ('```json\n{"name":"wait"}\n```', "model_output_markdown"),
    (' {"name":"wait"}', "model_output_surrounding_whitespace"),
    ('I will wait.', "model_output_invalid_json"),
    ('[{"name":"wait"}]', "model_output_not_object"),
    ('{"target":"door.front"}', "model_output_invalid_name"),
    ('{"name":"report","parameters":"done"}', "model_output_invalid_parameters"),
    ('{"name":"wait","reason":"safe"}', "model_output_unknown_fields"),
])
def test_parser_rejects_non_contract_output(raw, code):
    with pytest.raises(Exception) as caught: StrictActionParser().parse(raw)
    assert caught.value.code == code


def test_prompt_contains_tools_and_previous_observation():
    payload = json.loads(ActionPromptBuilder().build(context()))
    assert payload["task"]["command"] == "Do not open the door."
    assert len(payload["tools"]) == 2
    assert payload["previous_observations"][0]["code"] == "TOO_FAR"


def test_invalid_model_output_becomes_observation_without_mutation():
    engine = EpisodeEngine(door_visitor_world(), ModelPolicy(ScriptedTextProvider(["I opened it."])), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
    task = engine.submit_command(door_visitor_task(max_steps=2)); observation = engine.tick()
    assert not observation.success and observation.code == "model_output_invalid_json"
    assert engine.world.objects["door.front"].state == "closed" and task.status is TaskStatus.ACTIVE


def test_scripted_model_contract_completes_reference_episode():
    f = claimed_fact("Xiaoman")
    responses = [
        '{"name":"move_to","target":"door.front","parameters":{"acceptance_radius":80}}',
        '{"name":"listen_at","target":"door.front","parameters":{"duration":2}}',
        '{"name":"ask_through","target":"visitor.xiaoman","parameters":{"barrier_id":"door.front","topic":"identity"}}',
        '{"name":"move_to","target":"player","parameters":{"acceptance_radius":120}}',
        json.dumps({"name":"report","target":"player","parameters":{"text":"The visitor claims to be Xiaoman.","facts":[f]}}, separators=(",", ":")),
    ]
    provider = ScriptedTextProvider(responses)
    engine = EpisodeEngine(door_visitor_world(), ModelPolicy(provider), Gateway(), SimulatedExecutor(), DoorVisitorEvaluator())
    task = engine.submit_command(door_visitor_task()); engine.run_until_terminal()
    assert task.status is TaskStatus.SUCCEEDED and len(provider.prompts) == 5


def test_openai_provider_normalizes_urls():
    assert OpenAICompatibleProvider("http://localhost:8000", "model").chat_completions_url == "http://localhost:8000/v1/chat/completions"


def test_openai_provider_posts_expected_request(monkeypatch):
    captured = {}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self): return b'{"choices":[{"message":{"content":"{\\"name\\":\\"wait\\"}"}}]}'
    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url; captured["body"] = json.loads(req.data.decode()); return FakeResponse()
    monkeypatch.setattr(request, "urlopen", fake_urlopen)
    result = OpenAICompatibleProvider("http://localhost:8000/v1", "qwen-test", api_key="test").complete("prompt")
    assert result == '{"name":"wait"}' and captured["body"]["model"] == "qwen-test"
