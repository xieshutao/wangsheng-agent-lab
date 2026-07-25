from __future__ import annotations

from dataclasses import dataclass
import json

from .models import PolicyContext


@dataclass(frozen=True, slots=True)
class ActionPromptBuilder:
    """Builds a deterministic, machine-readable prompt for one action."""

    schema_version: str = "wangsheng.action.v1"

    def build(self, context: PolicyContext) -> str:
        payload = {
            "schema_version": self.schema_version,
            "instruction": (
                "Choose exactly one next action. Return only one compact JSON object. "
                "Do not use Markdown. Do not claim that an action succeeded. "
                "World truth comes only from observations."
            ),
            "output_schema": {
                "name": "string; required; must be one of available_actions",
                "target": "string or null",
                "parameters": "object",
            },
            "task": {
                "task_id": context.task_id,
                "command": context.command,
                "step_count": context.step_count,
            },
            "available_actions": list(context.available_actions),
            "forbidden_actions": list(context.forbidden_actions),
            "world": context.world,
            "previous_observations": list(context.observations),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
