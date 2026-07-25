from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Protocol

from .errors import PolicyOutputError
from .models import Action, PolicyContext
from .parser import StrictActionParser
from .prompting import ActionPromptBuilder, ToolCallingPromptBuilder
from .providers import TextProvider, ToolCallingProvider, ToolCallingTurn


class Policy(Protocol):
    def next_action(self, context: PolicyContext) -> Action:
        """Return exactly one action for the current tick."""


@dataclass(slots=True)
class ScriptedPolicy:
    actions: list[Action]
    _index: int = field(default=0, init=False)

    def next_action(self, context: PolicyContext) -> Action:
        if self._index >= len(self.actions):
            return Action(name="wait")
        action = self.actions[self._index]
        self._index += 1
        return action


@dataclass(slots=True)
class RecordingPolicy:
    inner: Policy
    contexts: list[PolicyContext] = field(default_factory=list)

    def next_action(self, context: PolicyContext) -> Action:
        self.contexts.append(context)
        return self.inner.next_action(context)

    @property
    def last_model_metadata(self) -> dict[str, Any] | None:
        return getattr(self.inner, "last_model_metadata", None)


@dataclass(slots=True)
class ModelPolicy:
    """Fallback text-JSON policy retained for deterministic regression tests."""

    provider: TextProvider
    parser: StrictActionParser = field(default_factory=StrictActionParser)
    prompt_builder: ActionPromptBuilder = field(default_factory=ActionPromptBuilder)
    raw_outputs: list[str] = field(default_factory=list)

    def next_action(self, context: PolicyContext) -> Action:
        prompt = self.prompt_builder.build(context)
        raw_output = self.provider.complete(prompt)
        self.raw_outputs.append(raw_output)
        return self.parser.parse(raw_output)


@dataclass(slots=True)
class NativeToolCallingPolicy:
    """One native API tool call becomes one Action.

    Ordinary assistant text is never parsed as an action. Multiple tool calls
    are rejected because the runtime executes at most one action per tick.
    """

    provider: ToolCallingProvider
    prompt_builder: ToolCallingPromptBuilder = field(default_factory=ToolCallingPromptBuilder)
    default_tool_choice: str | dict[str, Any] | None = "required"
    turns: list[ToolCallingTurn] = field(default_factory=list)
    last_turn: ToolCallingTurn | None = None

    def request_turn(
        self,
        context: PolicyContext,
        *,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ToolCallingTurn:
        messages = self.prompt_builder.build_messages(context)
        tools = [_api_tool_schema(schema) for schema in context.tool_schemas]
        selected_choice = self.default_tool_choice if tool_choice is None else tool_choice
        turn = self.provider.complete_tool_call(
            messages=messages,
            tools=tools,
            tool_choice=selected_choice,
        )
        self.turns.append(turn)
        self.last_turn = turn
        return turn

    def next_action(self, context: PolicyContext) -> Action:
        return self.action_from_turn(self.request_turn(context))

    @staticmethod
    def action_from_turn(turn: ToolCallingTurn) -> Action:
        raw_output = json.dumps(turn.response_message, ensure_ascii=False, sort_keys=True)
        if not turn.tool_calls:
            raise PolicyOutputError(
                "model_no_tool_call",
                "The model returned no native tool call for an active task.",
                raw_output=raw_output,
            )
        if len(turn.tool_calls) != 1:
            raise PolicyOutputError(
                "model_multiple_tool_calls",
                "The model must return exactly one tool call per tick.",
                raw_output=raw_output,
            )
        call = turn.tool_calls[0]
        arguments = dict(call.arguments)
        target = arguments.pop("target_id", None)
        if target is not None and (not isinstance(target, str) or not target.strip()):
            raise PolicyOutputError(
                "model_invalid_tool_target",
                "target_id must be a non-empty string when present.",
                raw_output=raw_output,
            )
        return Action(
            name=call.name,
            target=target,
            parameters=arguments,
            action_id=call.call_id,
        )

    @property
    def last_model_metadata(self) -> dict[str, Any] | None:
        if self.last_turn is None:
            return None
        return {
            "prompt_version": self.prompt_builder.prompt_version,
            **self.last_turn.metadata(),
        }


def _api_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove WangSheng-only metadata before sending a schema to model APIs."""

    return {
        "type": schema["type"],
        "function": schema["function"],
    }
