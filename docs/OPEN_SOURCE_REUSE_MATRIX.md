# Open-source reuse matrix

This file records whether WangSheng should depend on, adapt, vendor or only study an external project. A project is not considered "used" merely because its architecture influenced design.

| Project | Intended role | Reuse mode | Current status | Boundary that must remain WangSheng-owned |
|---|---|---|---|---|
| Qwen-Agent | Qwen-specific message/tool-call translation | Thin optional adapter | Reviewed, not installed | WorldState, Gateway, Executor, Evaluator, memory authority |
| llama.cpp | GGUF inference and local OpenAI-compatible service | Direct pinned dependency later | Deferred until local-model gate | Game rules and task loop |
| Llama-Unreal | UE-native local/remote inference bridge | Independent plugin spike | Deferred until UE graybox | NPC Core and authoritative world state |
| Concordia | Intent-versus-world-outcome separation | Architecture reference | Principle adopted | Deterministic physical and hard-rule adjudication |
| Gigax | Compact game-NPC context layout | Data-layout reference | Affordance/context ideas adopted locally | Tool protocol and world semantics |
| ORAK | Repeated experiments and failure taxonomy | Evaluation reference | Reporting pattern adopted locally | Runtime and game execution |
| AI Town | Shared multi-agent state and transaction ideas | Later source study | Deferred until second NPC | UE/world transaction authority |
| SOTOPIA | Social-behavior evaluation dimensions | Later evaluation reference | Deferred | Core task correctness and safety |
| Dendron | LLM nodes inside deterministic behavior structure | Design reference | Planned for UE StateTree/Behavior Tree | UE movement, animation and routine behavior |

## Decision rules

### Direct dependency

Use when the external project solves a generic technical problem with a compatible control boundary. Pin an exact release or commit and preserve its license.

### Thin adapter

Use when the project is useful only at the provider/protocol edge. External objects must not enter WangSheng domain models.

### Vendored module

Use only for a small, independently testable module when a normal dependency is impractical. Preserve upstream path, commit, license and local diff under `vendor/` and `THIRD_PARTY_NOTICES.md`.

### Architecture reference

Use when runtime ownership differs. No source is copied; the repository records the concept and implements a project-specific contract.

## v0.4.1 source provenance

No external source code is copied into v0.4.1. The new model-visibility and affordance code is WangSheng-specific because it depends on the project's hidden identity, knowledge-access and world-action rules.

The next direct open-source spike should be Llama-Unreal, but only after the text NPC Core demonstrates multi-step replanning with one cloud model.
