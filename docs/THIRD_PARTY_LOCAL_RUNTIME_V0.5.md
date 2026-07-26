# v0.5 local-runtime provenance

This file records provenance requirements; it does not vendor or redistribute any third-party binary or model.

| Component | Formal role | Frozen identifier | Repository / source | Repository contents |
|---|---|---|---|---|
| llama.cpp | Local GGUF inference and OpenAI-compatible service | release `b9637`, reference commit `aedb2a5` | `ggml-org/llama.cpp` | Not vendored; binary hash recorded privately |
| Qwen3-8B GGUF | Capability profile | official `Qwen3-8B-Q4_K_M.gguf` | `Qwen/Qwen3-8B-GGUF` | Not stored in Git; model hash and source revision recorded privately |
| Qwen3-4B GGUF | Shipping-budget profile | official `Qwen3-4B-Q5_K_M.gguf` | `Qwen/Qwen3-4B-GGUF` | Not stored in Git; model hash and source revision recorded privately |
| Qwen3-8B Q5 GGUF | Conditional quantization profile | official `Qwen3-8B-Q5_K_M.gguf` | `Qwen/Qwen3-8B-GGUF` | Not stored in Git; only run under SPEC conditions |

Before formal evidence is accepted, the operator must archive the upstream license files and repository revision metadata in private provenance records. WangSheng does not copy llama.cpp source, Qwen model weights or conversion scripts into this repository.
