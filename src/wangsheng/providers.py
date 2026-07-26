from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from time import perf_counter, sleep
from typing import Any, Callable, Protocol
from urllib import error, request
from urllib.parse import urlsplit, urlunsplit

from .errors import ProviderError


class TextProvider(Protocol):
    def complete(self, prompt: str) -> str:
        """Return one raw text completion."""


class ToolCallingProvider(Protocol):
    def complete_tool_call(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> "ToolCallingTurn":
        """Return one native tool-calling turn without executing any tool."""


@dataclass(frozen=True, slots=True)
class NativeToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(
                    self.arguments,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        }


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> "ProviderUsage":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            prompt_tokens=_optional_int(payload.get("prompt_tokens")),
            completion_tokens=_optional_int(payload.get("completion_tokens")),
            total_tokens=_optional_int(payload.get("total_tokens")),
        )

    def to_dict(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class ToolCallingTurn:
    content: str | None
    tool_calls: tuple[NativeToolCall, ...]
    finish_reason: str | None
    model: str
    request_id: str | None
    usage: ProviderUsage
    latency_ms: float
    raw_response_hash: str
    response_message: dict[str, Any]
    provider_name: str = "openai-compatible"
    attempt_count: int = 1
    provider_metrics: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "request_id": self.request_id,
            "finish_reason": self.finish_reason,
            "tool_call_count": len(self.tool_calls),
            "tool_call_ids": [call.call_id for call in self.tool_calls],
            "usage": self.usage.to_dict(),
            "latency_ms": round(self.latency_ms, 3),
            "raw_response_hash": self.raw_response_hash,
            "attempt_count": self.attempt_count,
            "provider_metrics": dict(self.provider_metrics),
        }


@dataclass(slots=True)
class ScriptedTextProvider:
    """Deterministic provider used for fallback text-contract tests."""

    responses: list[str]
    prompts: list[str] = field(default_factory=list)
    _index: int = field(default=0, init=False)

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._index >= len(self.responses):
            raise ProviderError("provider_exhausted", "No scripted response remains.")
        response = self.responses[self._index]
        self._index += 1
        return response


@dataclass(slots=True)
class ScriptedToolCallingProvider:
    """Deterministic native-tool provider used by unit and experiment tests."""

    turns: list[ToolCallingTurn]
    requests: list[dict[str, Any]] = field(default_factory=list)
    _index: int = field(default=0, init=False)

    def complete_tool_call(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ToolCallingTurn:
        self.requests.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        if self._index >= len(self.turns):
            raise ProviderError("provider_exhausted", "No scripted tool-calling turn remains.")
        turn = self.turns[self._index]
        self._index += 1
        return turn


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProvider:
    """Fallback text client retained for compatibility and negative tests."""

    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    max_tokens: int = 256

    def complete(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        payload = _post_json(
            url=self.chat_completions_url,
            body=body,
            api_key=self.api_key or os.getenv("WANGSHENG_MODEL_API_KEY"),
            timeout_seconds=self.timeout_seconds,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )[0]

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "provider_invalid_response",
                "Provider response did not contain choices[0].message.content.",
            ) from exc

        if not isinstance(content, str):
            raise ProviderError(
                "provider_invalid_content",
                "Provider message content must be a string.",
            )
        return content

    @property
    def chat_completions_url(self) -> str:
        return normalize_chat_completions_url(self.base_url)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleToolCallingProvider:
    """Native tool-call client for cloud APIs, vLLM and llama.cpp servers.

    This class deliberately does not execute tools and does not parse ordinary
    assistant prose into actions. It accepts only the structured
    ``choices[0].message.tool_calls`` field.
    """

    base_url: str
    model: str
    api_key: str | None = None
    api_key_env: str = "WANGSHENG_CLOUD_API_KEY"
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = 256
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    send_parallel_tool_calls: bool = True
    extra_body: dict[str, Any] = field(default_factory=dict)
    provider_name: str = "openai-compatible"

    def complete_tool_call(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ToolCallingTurn:
        if not messages:
            raise ProviderError("provider_invalid_request", "At least one message is required.")

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if self.top_p is not None:
            if not 0 <= self.top_p <= 1:
                raise ProviderError(
                    "provider_invalid_request",
                    "top_p must be between 0 and 1 when provided.",
                )
            body["top_p"] = self.top_p
        if tools and tool_choice is not None:
            body["tool_choice"] = tool_choice
        if tools and self.send_parallel_tool_calls:
            body["parallel_tool_calls"] = False
        overlap = set(body) & set(self.extra_body)
        if overlap:
            raise ProviderError(
                "provider_invalid_request",
                f"extra_body cannot override reserved fields: {sorted(overlap)}.",
            )
        body.update(self.extra_body)

        key = self.api_key or os.getenv(self.api_key_env)
        payload, raw, latency_ms, attempt_count = _post_json(
            url=self.chat_completions_url,
            body=body,
            api_key=key,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            retry_backoff_seconds=self.retry_backoff_seconds,
        )
        return self._parse_turn(
            payload=payload,
            raw=raw,
            latency_ms=latency_ms,
            attempt_count=attempt_count,
        )

    def _parse_turn(
        self,
        *,
        payload: dict[str, Any],
        raw: str,
        latency_ms: float,
        attempt_count: int,
    ) -> ToolCallingTurn:
        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "provider_invalid_response",
                "Provider response did not contain choices[0].message.",
            ) from exc
        if not isinstance(message, dict):
            raise ProviderError(
                "provider_invalid_response",
                "choices[0].message must be an object.",
            )

        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ProviderError(
                "provider_invalid_content",
                "Assistant message content must be a string or null.",
            )

        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls is None:
            raw_tool_calls = []
        if not isinstance(raw_tool_calls, list):
            raise ProviderError(
                "provider_invalid_tool_calls",
                "Assistant message tool_calls must be an array.",
            )
        tool_calls = tuple(
            self._parse_tool_call(item, index)
            for index, item in enumerate(raw_tool_calls)
        )

        response_message = {
            "role": message.get("role", "assistant"),
            "content": content,
            "tool_calls": [call.to_dict() for call in tool_calls],
        }
        return ToolCallingTurn(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason") if isinstance(choice, dict) else None,
            model=str(payload.get("model") or self.model),
            request_id=str(payload["id"]) if payload.get("id") is not None else None,
            usage=ProviderUsage.from_payload(payload.get("usage")),
            latency_ms=latency_ms,
            raw_response_hash=sha256(raw.encode("utf-8")).hexdigest(),
            response_message=response_message,
            provider_name=self.provider_name,
            attempt_count=attempt_count,
            provider_metrics=_extract_provider_metrics(payload),
        )

    @staticmethod
    def _parse_tool_call(item: Any, index: int) -> NativeToolCall:
        if not isinstance(item, dict):
            raise ProviderError(
                "provider_invalid_tool_call",
                f"tool_calls[{index}] must be an object.",
            )
        call_type = item.get("type", "function")
        if call_type != "function":
            raise ProviderError(
                "provider_invalid_tool_call",
                f"tool_calls[{index}].type must be 'function'.",
            )
        call_id = item.get("id")
        function = item.get("function")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ProviderError(
                "provider_invalid_tool_call",
                f"tool_calls[{index}].id must be a non-empty string.",
            )
        if not isinstance(function, dict):
            raise ProviderError(
                "provider_invalid_tool_call",
                f"tool_calls[{index}].function must be an object.",
            )
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProviderError(
                "provider_invalid_tool_call",
                f"tool_calls[{index}].function.name must be a non-empty string.",
            )
        raw_arguments = function.get("arguments", "{}")
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                excerpt = raw_arguments[:512]
                raise ProviderError(
                    "provider_invalid_tool_arguments",
                    f"tool_calls[{index}] arguments are not valid JSON.",
                    details={
                        "tool_call_index": index,
                        "argument_excerpt": excerpt,
                        "json_error_position": exc.pos,
                        "json_error_message": exc.msg,
                    },
                ) from exc
        elif isinstance(raw_arguments, dict):
            arguments = dict(raw_arguments)
        else:
            raise ProviderError(
                "provider_invalid_tool_arguments",
                f"tool_calls[{index}] arguments must be a JSON string or object.",
                details={
                    "tool_call_index": index,
                    "argument_type": type(raw_arguments).__name__,
                },
            )
        if not isinstance(arguments, dict):
            raise ProviderError(
                "provider_invalid_tool_arguments",
                f"tool_calls[{index}] arguments must decode to an object.",
                details={
                    "tool_call_index": index,
                    "decoded_type": type(arguments).__name__,
                },
            )
        return NativeToolCall(call_id=call_id, name=name, arguments=arguments)

    @property
    def chat_completions_url(self) -> str:
        return normalize_chat_completions_url(self.base_url)

    def public_config(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "base_url": _sanitize_base_url(self.base_url),
            "model": self.model,
            "api_key_env": self.api_key_env,
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "max_retries": self.max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "send_parallel_tool_calls": self.send_parallel_tool_calls,
            "extra_body_keys": sorted(self.extra_body),
        }


def _extract_provider_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded set of provider timing counters when available.

    llama.cpp commonly returns a top-level ``timings`` object. Cloud
    providers may omit it. Unknown nested structures are ignored so raw
    provider payloads do not leak into traces.
    """

    raw = payload.get("timings")
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "cache_n",
        "prompt_n",
        "prompt_ms",
        "prompt_per_token_ms",
        "prompt_per_second",
        "predicted_n",
        "predicted_ms",
        "predicted_per_token_ms",
        "predicted_per_second",
    }
    result: dict[str, Any] = {}
    for key in sorted(allowed):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
    return {"timings": result} if result else {}


def normalize_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _post_json(
    *,
    url: str,
    body: dict[str, Any],
    api_key: str | None,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
) -> tuple[dict[str, Any], str, float, int]:
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    retryable_statuses = {408, 409, 429, 500, 502, 503, 504}
    started = perf_counter()
    attempt = 0
    while True:
        attempt += 1
        req = request.Request(url, data=encoded, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            break
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in retryable_statuses and attempt <= max_retries:
                sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            safe_detail = _redact(detail[:1000], api_key)
            raise ProviderError(
                "provider_http_error",
                f"Provider returned HTTP {exc.code}: {safe_detail}",
            ) from exc
        except error.URLError as exc:
            if attempt <= max_retries:
                sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            raise ProviderError(
                "provider_connection_error",
                f"Could not reach provider: {exc.reason}",
            ) from exc
        except TimeoutError as exc:
            if attempt <= max_retries:
                sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            raise ProviderError("provider_timeout", "Provider request timed out.") from exc
    latency_ms = (perf_counter() - started) * 1000

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "provider_invalid_json",
            "Provider response was not valid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderError(
            "provider_invalid_response",
            "Provider response must be a JSON object.",
        )
    return payload, raw, latency_ms, attempt


def _redact(text: str, secret: str | None) -> str:
    if secret:
        return text.replace(secret, "[REDACTED]")
    return text


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _sanitize_base_url(base_url: str) -> str:
    if "://" not in base_url:
        return base_url.split("?", 1)[0].split("#", 1)[0]
    parts = urlsplit(base_url)
    hostname = parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
