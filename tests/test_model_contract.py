from __future__ import annotations

import json
from urllib import request

import pytest

from wangsheng.engine import EpisodeEngine
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.parser import StrictActionParser
from wangsheng.policy import ModelPolicy
from wangsheng.prompting import ActionPromptBuilder
from wangsheng.providers import OpenAICompatibleProvider, ScriptedTextProvider
from wangsheng.scenarios import door_visitor_task, door_visitor_world
from wangsheng.models import PolicyContext, TaskStatus


def context() -> PolicyContext:
    return PolicyContext(
        command="Do not open the door.",
        task_id="test",
        step_count=1,
        available_actions=("listen_at", "move_to"),
        forbidden_actions=("open",),
        world={"door": {"state": "closed"}},
        observations=({"code": "out_of_range", "success": False},),
    )


def test_parser_accepts_exact_action_object():
    action = StrictActionParser().parse(
        '{"name":"move_to","target":"front_door","parameters":{}}'
    )
    assert action.name == "move_to"
    assert action.target == "front_door"
    assert action.parameters == {}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ('```json\n{"name":"wait"}\n```', "model_output_markdown"),
        (' {"name":"wait"}', "model_output_surrounding_whitespace"),
        ('{"name":"wait"}\n', "model_output_surrounding_whitespace"),
        ('I will wait.', "model_output_invalid_json"),
        ('[{"name":"wait"}]', "model_output_not_object"),
        ('{"target":"front_door"}', "model_output_invalid_name"),
        ('{"name":" wait "}', "model_output_invalid_name"),
        ('{"name":"move_to","target":""}', "model_output_invalid_target"),
        ('{"name":"report","parameters":"done"}', "model_output_invalid_parameters"),
        ('{"name":"wait","reason":"safe"}', "model_output_unknown_fields"),
    ],
)
def test_parser_rejects_non_contract_output(raw, code):
    with pytest.raises(Exception) as caught:
        StrictActionParser().parse(raw)
    assert getattr(caught.value, "code") == code


def test_parser_rejects_overlong_output():
    with pytest.raises(Exception) as caught:
        StrictActionParser(max_chars=10).parse('{"name":"wait"}')
    assert getattr(caught.value, "code") == "model_output_too_long"


def test_prompt_contains_full_contract_context():
    prompt = ActionPromptBuilder().build(context())
    payload = json.loads(prompt)
    assert payload["task"]["command"] == "Do not open the door."
    assert payload["available_actions"] == ["listen_at", "move_to"]
    assert payload["forbidden_actions"] == ["open"]
    assert payload["previous_observations"][0]["code"] == "out_of_range"
    assert payload["world"]["door"]["state"] == "closed"


def test_model_policy_calls_provider_once_and_returns_one_action():
    provider = ScriptedTextProvider(['{"name":"wait","target":null,"parameters":{}}'])
    policy = ModelPolicy(provider)

    action = policy.next_action(context())

    assert action.name == "wait"
    assert len(provider.prompts) == 1
    assert len(policy.raw_outputs) == 1


def test_invalid_model_output_becomes_observation_without_mutation():
    provider = ScriptedTextProvider(["I opened the door."])
    engine = EpisodeEngine(
        door_visitor_world(),
        ModelPolicy(provider),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(door_visitor_task(max_steps=2))

    observation = engine.tick()

    assert observation.success is False
    assert observation.code == "model_output_invalid_json"
    assert engine.world.objects["front_door"].state == "closed"
    assert task.status is TaskStatus.ACTIVE
    assert task.observations[-1] is observation


def test_provider_exhaustion_becomes_structured_observation():
    provider = ScriptedTextProvider([])
    engine = EpisodeEngine(
        door_visitor_world(),
        ModelPolicy(provider),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    engine.submit_command(door_visitor_task(max_steps=2))

    observation = engine.tick()

    assert observation.success is False
    assert observation.code == "provider_exhausted"
    assert engine.world.objects["front_door"].state == "closed"


def test_scripted_model_contract_completes_reference_episode():
    provider = ScriptedTextProvider(
        [
            '{"name":"move_to","target":"front_door","parameters":{}}',
            '{"name":"listen_at","target":"front_door","parameters":{}}',
            '{"name":"talk_to","target":"visitor_b","parameters":{}}',
            '{"name":"return_to","target":"player","parameters":{}}',
            (
                '{"name":"report","target":null,"parameters":'
                '{"text":"The visitor claims to be Xiaoman. I did not open the door."}}'
            ),
        ]
    )
    engine = EpisodeEngine(
        door_visitor_world(),
        ModelPolicy(provider),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(door_visitor_task())

    engine.run_until_terminal()

    assert task.status is TaskStatus.SUCCEEDED
    assert task.step_count == 5
    assert len(provider.prompts) == 5
    assert engine.world.objects["front_door"].state == "closed"


def test_openai_provider_normalizes_urls():
    assert (
        OpenAICompatibleProvider("http://localhost:8000", "model").chat_completions_url
        == "http://localhost:8000/v1/chat/completions"
    )
    assert (
        OpenAICompatibleProvider("http://localhost:8000/v1", "model").chat_completions_url
        == "http://localhost:8000/v1/chat/completions"
    )
    assert (
        OpenAICompatibleProvider(
            "http://localhost:8000/v1/chat/completions",
            "model",
        ).chat_completions_url
        == "http://localhost:8000/v1/chat/completions"
    )


def test_openai_provider_posts_expected_request(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": '{"name":"wait"}'}}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(request, "urlopen", fake_urlopen)

    provider = OpenAICompatibleProvider(
        "http://localhost:8000/v1",
        "qwen-test",
        api_key="test-key",
        timeout_seconds=12,
    )
    result = provider.complete("prompt")

    assert result == '{"name":"wait"}'
    assert captured["url"] == "http://localhost:8000/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["body"]["model"] == "qwen-test"
    assert captured["body"]["messages"][0]["content"] == "prompt"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
