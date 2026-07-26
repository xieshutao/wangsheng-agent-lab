# WangSheng Agent Lab baseline status

## Current source candidate

- **Version**: `v0.4.3`
- **Commit**: `3dc5ac5f85135c6f2e66c6f34d78d2225bd80ecb`
- **Branch**: `feat/failure-aware-replanning-v0.4.3`
- **Status**: Eligible for expanded model validation
- **Runtime**: Python 3.10+
- **Runtime third-party dependencies**: none

## Frozen real-model evidence

### v0.4.2 DeepSeek 20-Episode (baseline)
- pass: 7/20, 35%
- protocol valid: 18/20 (90%)
- grounded: 15/20 (75%)
- hard violations: 0 | hallucinated targets: 0
- provider errors: 2
- total tokens: 439,097

### v0.4.3 DeepSeek 25-Episode (current)
| Set | Passed | Rate |
|-----|--------|:----:|
| Regression (original 20) | 18 | 90.0% |
| Holdout (new 5) | 5 | 100% |
| **Overall** | **23** | **92.0%** |

- protocol valid: 25/25 (100%)
- grounded: 25/25 (100%)
- objective completed: 24/25 (96%)
- hard violations: 0 | hallucinated targets: 0
- knowledge violations: 0 | loops: 0
- provider errors: 0 | policy errors: 0
- total tokens: 179,922 (67.8% reduction from v0.4.2)

**Package**: `results/v043-deepseek-25episodes.tar.gz`
**SHA-256**: `d168a037f95c658c6ade5ecb69f068ae41d8bf9440d67b581dd0c8bad1bd6bbc`

## Verified v0.4.3 source scope

- 104 automated tests
- 20/20 original deterministic scenarios
- 5/5 frozen holdout scenarios
- zero executed hard violations
- zero incomplete traces
- Golden Trace exact replay

## Next gate

1. Archive v0.4.3 as final cloud-era checkpoint.
2. Merge to `main`, tag `v0.4.3`.
3. Begin **v0.5 Local Model Baseline**: llama.cpp + GGUF on RTX 4060.
   - Test 4-bit/5-bit quantized 7B-9B models
   - Same strict Tool Calling contract
   - Measure throughput, latency, memory, pass rate
