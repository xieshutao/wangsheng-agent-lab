from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import Action, PolicyContext
from .parser import StrictActionParser
from .prompting import ActionPromptBuilder
from .providers import TextProvider


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


@dataclass(slots=True)
class ModelPolicy:
    """One provider call -> one strict JSON object -> one Action."""

    provider: TextProvider
    parser: StrictActionParser = field(default_factory=StrictActionParser)
    prompt_builder: ActionPromptBuilder = field(default_factory=ActionPromptBuilder)
    raw_outputs: list[str] = field(default_factory=list)

    def next_action(self, context: PolicyContext) -> Action:
        prompt = self.prompt_builder.build(context)
        raw_output = self.provider.complete(prompt)
        self.raw_outputs.append(raw_output)
        return self.parser.parse(raw_output)
