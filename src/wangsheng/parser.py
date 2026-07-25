from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .errors import PolicyOutputError
from .models import Action


@dataclass(frozen=True, slots=True)
class StrictActionParser:
    """Parses exactly one JSON object into exactly one Action.

    The parser deliberately rejects Markdown fences, prose, arrays, unknown
    top-level fields, and malformed parameter types.
    """

    max_chars: int = 4096
    allowed_fields: frozenset[str] = frozenset({"name", "target", "parameters"})

    def parse(self, raw_output: str) -> Action:
        if not isinstance(raw_output, str):
            raise PolicyOutputError(
                "model_output_not_text",
                "Model output must be a string.",
                raw_output=repr(raw_output),
            )

        if len(raw_output) > self.max_chars:
            raise PolicyOutputError(
                "model_output_too_long",
                f"Model output exceeds {self.max_chars} characters.",
                raw_output=raw_output[: self.max_chars],
            )

        if raw_output != raw_output.strip():
            raise PolicyOutputError(
                "model_output_surrounding_whitespace",
                "Model output must contain only the JSON object, without surrounding whitespace.",
                raw_output=raw_output,
            )

        if raw_output.startswith("```") or raw_output.endswith("```"):
            raise PolicyOutputError(
                "model_output_markdown",
                "Markdown code fences are not allowed.",
                raw_output=raw_output,
            )

        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise PolicyOutputError(
                "model_output_invalid_json",
                f"Invalid JSON at line {exc.lineno}, column {exc.colno}.",
                raw_output=raw_output,
            ) from exc

        if not isinstance(payload, dict):
            raise PolicyOutputError(
                "model_output_not_object",
                "The top-level JSON value must be an object.",
                raw_output=raw_output,
            )

        unknown_fields = set(payload) - self.allowed_fields
        if unknown_fields:
            raise PolicyOutputError(
                "model_output_unknown_fields",
                f"Unknown top-level fields: {sorted(unknown_fields)}.",
                raw_output=raw_output,
            )

        name = payload.get("name")
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise PolicyOutputError(
                "model_output_invalid_name",
                "'name' must be a non-empty string without surrounding whitespace.",
                raw_output=raw_output,
            )

        target = payload.get("target")
        if target is not None:
            if not isinstance(target, str) or not target.strip() or target != target.strip():
                raise PolicyOutputError(
                    "model_output_invalid_target",
                    "'target' must be null or a non-empty string without surrounding whitespace.",
                    raw_output=raw_output,
                )

        parameters: Any = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            raise PolicyOutputError(
                "model_output_invalid_parameters",
                "'parameters' must be a JSON object.",
                raw_output=raw_output,
            )

        return Action(name=name, target=target, parameters=parameters)
