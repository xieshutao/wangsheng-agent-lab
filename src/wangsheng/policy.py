from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol
from .models import Action, PolicyContext

class Policy(Protocol):
    def next_action(self, context: PolicyContext) -> Action: ...

@dataclass(slots=True)
class ScriptedPolicy:
    actions: list[Action]
    _index: int = field(default=0, init=False)
    def next_action(self, context: PolicyContext) -> Action:
        if self._index >= len(self.actions): return Action(name="wait")
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
