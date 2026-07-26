from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from urllib import error

import pytest

from wangsheng.engine import EpisodeEngine
from wangsheng.errors import PolicyOutputError, ProviderError
from wangsheng.evaluator import DoorVisitorEvaluator
from wangsheng.executor import SimulatedExecutor
from wangsheng.gateway import Gateway
from wangsheng.policy import NativeToolCallingPolicy
from wangsheng.providers import (
    NativeToolCall,
    OpenAICompatibleToolCallingProvider,
    ProviderUsage,
    ScriptedToolCallingProvider,
    ToolCallingTurn,
    normalize_chat_completions_url,
)
from wangsheng.scenarios import door_visitor_task, door_visitor_world
from wangsheng.trace import JsonlTraceRecorder, load_jsonl


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.raw


def make_turn(*calls: NativeToolCall, content: str | None = None) -> ToolCallingTurn:
    return ToolCallingTurn(
        content=content,
        tool_calls=tuple(calls),
        finish_reason="tool_calls" if calls else "stop",
        model="test-model",
        request_id="req-test",
        usage=ProviderUsage(10, 4, 14),
        latency_ms=12.5,
        raw_response_hash="a" * 64,
        response_message={
            "role": "assistant",
            "content": content,
            "tool_calls": [call.to_dict() for call in calls],
        },
    )


def test_native_provider_parses_one_tool_call(monkeypatch) -> None:
    payload = {
        "id": "chatcmpl-1",
        "model": "cloud-model",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "move_to",
                                "arguments": '{"target_id":"door.front","acceptance_radius":80}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
    }
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["authorization"] = req.headers.get("Authorization")
        captured["timeout"] = timeout
        return FakeResponse(payload)

    monkeypatch.setattr("wangsheng.providers.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleToolCallingProvider(
        base_url="https://example.test/v1",
        model="cloud-model",
        api_key="secret",
        timeout_seconds=9,
        top_p=1.0,
        max_retries=0,
    )
    turn = provider.complete_tool_call(
        messages=[{"role": "user", "content": "test"}],
        tools=[{"type": "function", "function": {"name": "move_to", "parameters": {}}}],
        tool_choice="required",
    )
    assert turn.tool_calls[0].name == "move_to"
    assert turn.tool_calls[0].arguments["target_id"] == "door.front"
    assert turn.usage.total_tokens == 27
    assert turn.request_id == "chatcmpl-1"
    assert captured["body"]["tool_choice"] == "required"
    assert captured["body"]["top_p"] == 1.0
    assert captured["body"]["parallel_tool_calls"] is False
    assert captured["body"]["tools"][0]["type"] == "function"
    assert captured["authorization"] == "Bearer secret"
    assert captured["timeout"] == 9


def test_native_provider_accepts_object_arguments(monkeypatch) -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "wait", "arguments": {"seconds": 1}},
                        }
                    ],
                }
            }
        ]
    }
    monkeypatch.setattr(
        "wangsheng.providers.request.urlopen",
        lambda req, timeout: FakeResponse(payload),
    )
    provider = OpenAICompatibleToolCallingProvider("http://localhost:8000", "model", max_retries=0)
    turn = provider.complete_tool_call(
        messages=[{"role": "user", "content": "test"}],
        tools=[{"type": "function", "function": {"name": "wait", "parameters": {}}}],
    )
    assert turn.tool_calls[0].arguments == {"seconds": 1}


def test_native_provider_rejects_malformed_arguments(monkeypatch) -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "wait", "arguments": "{broken"},
                        }
                    ],
                }
            }
        ]
    }
    monkeypatch.setattr(
        "wangsheng.providers.request.urlopen",
        lambda req, timeout: FakeResponse(payload),
    )
    provider = OpenAICompatibleToolCallingProvider("http://localhost:8000", "model", max_retries=0)
    with pytest.raises(ProviderError) as exc:
        provider.complete_tool_call(
            messages=[{"role": "user", "content": "test"}],
            tools=[{"type": "function", "function": {"name": "wait", "parameters": {}}}],
        )
    assert exc.value.code == "provider_invalid_tool_arguments"


def test_native_policy_preserves_tool_call_id_and_extracts_target() -> None:
    turn = make_turn(
        NativeToolCall(
            "call-abc",
            "move_to",
            {"target_id": "door.front", "acceptance_radius": 80},
        )
    )
    policy = NativeToolCallingPolicy(ScriptedToolCallingProvider([turn]))
    engine = EpisodeEngine(
        door_visitor_world(),
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(door_visitor_task())
    action = policy.next_action(engine.build_context(task))
    assert action.action_id == "call-abc"
    assert action.target == "door.front"
    assert action.parameters == {"acceptance_radius": 80}


def test_native_policy_rejects_no_tool_call() -> None:
    policy = NativeToolCallingPolicy(ScriptedToolCallingProvider([make_turn(content="hello")]))
    engine = EpisodeEngine(
        door_visitor_world(),
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(door_visitor_task())
    with pytest.raises(PolicyOutputError) as exc:
        policy.next_action(engine.build_context(task))
    assert exc.value.code == "model_no_tool_call"


def test_native_policy_rejects_multiple_tool_calls() -> None:
    turn = make_turn(
        NativeToolCall("call-1", "observe", {"target_id": "door.front"}),
        NativeToolCall("call-2", "wait", {"seconds": 1}),
    )
    policy = NativeToolCallingPolicy(ScriptedToolCallingProvider([turn]))
    engine = EpisodeEngine(
        door_visitor_world(),
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(door_visitor_task())
    with pytest.raises(PolicyOutputError) as exc:
        policy.next_action(engine.build_context(task))
    assert exc.value.code == "model_multiple_tool_calls"


def test_policy_sends_api_schemas_without_wangsheng_extension() -> None:
    provider = ScriptedToolCallingProvider(
        [make_turn(NativeToolCall("call-1", "observe", {"target_id": "door.front"}))]
    )
    policy = NativeToolCallingPolicy(provider)
    engine = EpisodeEngine(
        door_visitor_world(),
        policy,
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
    )
    task = engine.submit_command(door_visitor_task())
    policy.next_action(engine.build_context(task))
    sent_tools = provider.requests[0]["tools"]
    assert sent_tools
    assert all(set(item) == {"type", "function"} for item in sent_tools)
    assert all("x-wangsheng" not in item for item in sent_tools)


def test_trace_contains_native_model_metadata(tmp_path: Path) -> None:
    turn = make_turn(
        NativeToolCall(
            "call-trace",
            "move_to",
            {"target_id": "door.front", "acceptance_radius": 80},
        )
    )
    recorder = JsonlTraceRecorder(tmp_path / "trace.jsonl", "episode-native")
    engine = EpisodeEngine(
        door_visitor_world(),
        NativeToolCallingPolicy(ScriptedToolCallingProvider([turn])),
        Gateway(),
        SimulatedExecutor(),
        DoorVisitorEvaluator(),
        trace_recorder=recorder,
    )
    engine.submit_command(door_visitor_task())
    observation = engine.tick()
    record = load_jsonl(tmp_path / "trace.jsonl")[0]
    assert observation.action.action_id == "call-trace"
    assert record["action_request"]["action_id"] == "call-trace"
    assert record["action_result"]["action_id"] == "call-trace"
    assert record["model"]["prompt_version"] == "wangsheng.tool_call_prompt.v3"
    assert record["model"]["tool_call_ids"] == ["call-trace"]


def test_provider_retries_retryable_http_error(monkeypatch) -> None:
    attempts = {"count": 0}
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "wait", "arguments": '{"seconds":1}'},
                        }
                    ],
                }
            }
        ]
    }

    def fake_urlopen(req, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise error.HTTPError(req.full_url, 429, "rate", {}, BytesIO(b"rate limited"))
        return FakeResponse(payload)

    monkeypatch.setattr("wangsheng.providers.request.urlopen", fake_urlopen)
    monkeypatch.setattr("wangsheng.providers.sleep", lambda seconds: None)
    provider = OpenAICompatibleToolCallingProvider(
        "http://localhost:8000",
        "model",
        max_retries=1,
        retry_backoff_seconds=0,
    )
    turn = provider.complete_tool_call(
        messages=[{"role": "user", "content": "test"}],
        tools=[{"type": "function", "function": {"name": "wait", "parameters": {}}}],
    )
    assert attempts["count"] == 2
    assert turn.attempt_count == 2


def test_provider_does_not_leak_api_key_in_http_error(monkeypatch) -> None:
    secret = "top-secret-token"

    def fake_urlopen(req, timeout):
        body = f"bad request echoed {secret}".encode()
        raise error.HTTPError(req.full_url, 400, "bad", {}, BytesIO(body))

    monkeypatch.setattr("wangsheng.providers.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleToolCallingProvider(
        "http://localhost:8000",
        "model",
        api_key=secret,
        max_retries=0,
    )
    with pytest.raises(ProviderError) as exc:
        provider.complete_tool_call(
            messages=[{"role": "user", "content": "test"}],
            tools=[{"type": "function", "function": {"name": "wait", "parameters": {}}}],
        )
    assert secret not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("http://localhost:8000", "http://localhost:8000/v1/chat/completions"),
        ("http://localhost:8000/v1", "http://localhost:8000/v1/chat/completions"),
        (
            "http://localhost:8000/v1/chat/completions",
            "http://localhost:8000/v1/chat/completions",
        ),
    ],
)
def test_normalize_chat_completions_url(base: str, expected: str) -> None:
    assert normalize_chat_completions_url(base) == expected


def test_public_config_redacts_url_credentials_and_query() -> None:
    provider = OpenAICompatibleToolCallingProvider(
        "https://user:password@example.test/v1?api_key=secret#fragment",
        "model",
    )
    config = provider.public_config()
    assert config["base_url"] == "https://example.test/v1"
    assert "password" not in json.dumps(config)
    assert "secret" not in json.dumps(config)


def test_native_provider_rejects_invalid_top_p_before_request() -> None:
    provider = OpenAICompatibleToolCallingProvider(
        "http://localhost:8000",
        "model",
        top_p=1.5,
        max_retries=0,
    )
    with pytest.raises(ProviderError) as exc:
        provider.complete_tool_call(
            messages=[{"role": "user", "content": "test"}],
            tools=[
                {
                    "type": "function",
                    "function": {"name": "wait", "parameters": {}},
                }
            ],
        )
    assert exc.value.code == "provider_invalid_request"
