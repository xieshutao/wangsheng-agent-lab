from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Protocol
from urllib import error, request

from .errors import ProviderError


class TextProvider(Protocol):
    def complete(self, prompt: str) -> str:
        """Return one raw text completion."""


@dataclass(slots=True)
class ScriptedTextProvider:
    """Deterministic provider used for contract tests."""

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


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProvider:
    """Minimal stdlib client for vLLM, llama.cpp server, Ollama, or cloud APIs."""

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
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        key = self.api_key or os.getenv("WANGSHENG_MODEL_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"

        req = request.Request(
            self.chat_completions_url,
            data=encoded,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(
                "provider_http_error",
                f"Provider returned HTTP {exc.code}: {detail[:500]}",
            ) from exc
        except error.URLError as exc:
            raise ProviderError(
                "provider_connection_error",
                f"Could not reach provider: {exc.reason}",
            ) from exc
        except TimeoutError as exc:
            raise ProviderError("provider_timeout", "Provider request timed out.") from exc

        try:
            payload: Any = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
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
        normalized = self.base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/chat/completions"
        return f"{normalized}/v1/chat/completions"
