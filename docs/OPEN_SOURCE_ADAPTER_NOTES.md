# Open-source adapter notes

## Qwen-Agent

Upstream: `QwenLM/Qwen-Agent`
License: Apache-2.0

Reviewed concepts and files:

- `qwen_agent/agents/fncall_agent.py`
- `BaseChatModel` function-calling boundary
- `BaseTool` tool definitions
- Qwen documentation for native/raw API tool calling

Adopted design:

- tools are passed separately from user content
- function arguments are treated as structured JSON
- provider-specific translation stays in the adapter layer
- tool results must be returned to the model in later multi-step work

Not adopted in v0.4.0:

- Qwen-Agent's full agent loop
- its memory, tool execution or task-completion ownership
- Qwen-Agent objects inside WorldState, Gateway, Executor or Evaluator

No Qwen-Agent source code is copied into this repository. The generic native adapter is implemented with the Python standard library so the 1 GB Hermes VPS does not need a large framework dependency. A Qwen-specific bridge remains optional for a later self-hosted Qwen backend that lacks raw native tool calls.

## ORAK

ORAK remains an evaluation reference rather than a runtime dependency. v0.4.0 adopts repeated fixed scenarios, raw run records and separated metrics, but does not import ORAK code or game environments.

## Concordia

The architecture adopts the principle that an agent proposes intent while the world authority decides outcomes. Unlike an LLM-driven Game Master, WangSheng keeps critical world decisions deterministic in Gateway, Executor and Evaluator.
