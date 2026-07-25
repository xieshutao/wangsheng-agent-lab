from __future__ import annotations

from dataclasses import dataclass
import json

from .models import PolicyContext


@dataclass(frozen=True, slots=True)
class ActionPromptBuilder:
    schema_version: str = "wangsheng.action.v2"

    def build(self, context: PolicyContext) -> str:
        payload = {
            "schema_version": self.schema_version,
            "instruction": (
                "Choose exactly one next action. Return only one compact JSON object. "
                "Do not claim success; world truth comes only from observations."
            ),
            "fallback_output_contract": {
                "name": "registered tool name",
                "target": "stable target id or null",
                "parameters": "object matching the selected tool schema",
            },
            "task": {"task_id": context.task_id, "command": context.command, "step_count": context.step_count},
            "intent": context.intent,
            "available_actions": list(context.available_actions),
            "forbidden_actions": list(context.forbidden_actions),
            "tools": list(context.tool_schemas),
            "world": context.world,
            "previous_observations": list(context.observations),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
