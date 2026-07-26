# Hermes execution: apply and verify v0.4.2

This phase applies the reviewed v0.4.2 patch to the frozen v0.4.1 repository, runs deterministic verification, commits, and pushes a dedicated branch. It must not call a real model API.

## Frozen base

- repository: `xieshutao/wangsheng-agent-lab`
- base branch: `feat/model-visible-world-v0.4.1`
- expected base commit: `585f0af7df568518e007c2c89b389c30b786a49a`
- target branch: `feat/cloud-episode-runner-v0.4.2`

## Prohibitions

- Do not modify the patch.
- Do not hand-edit source, tests, scenarios, prompts, expectations, or documentation.
- Do not run DeepSeek or any other real model.
- Do not merge `main`.
- Do not commit generated test outputs, API artifacts, caches, virtual environments, or credentials.
- Stop on any base-commit mismatch, patch failure, test failure, dirty unexpected file, or Golden Trace mismatch.

## Required verification

- `94 passed`
- deterministic scenarios: `20/20`
- deterministic hard violations: `0`
- trace incomplete: `0`
- Golden Trace: `passed=true`, `records_match=true`, `digest_match=true`
- package version: `0.4.2`

The user-facing Hermes prompt supplied with the artifact contains the exact shell procedure.
