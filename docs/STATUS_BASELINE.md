# WangSheng Agent Lab baseline status

## Current source candidate

- Version: `v0.4.3`
- Frozen base commit: `bfa50599cfffd20ff7584f097585d1ac9a81960a`
- Base branch: `feat/cloud-episode-runner-v0.4.2`
- Target branch: `feat/failure-aware-replanning-v0.4.3`
- Runtime: Python 3.10+
- Runtime third-party dependencies: none

## Frozen real-model evidence

v0.4.2 DeepSeek 20-Episode official result remains:

- pass: 7/20, 35%
- protocol valid: 18/20
- grounded: 15/20
- hard violations: 0
- hallucinated targets: 0
- provider errors: 2
- total tokens: 439,097

No v0.4.3 real-model experiment has been run.

## Verified v0.4.3 source scope

- 104 automated tests
- 20/20 original deterministic scenarios
- 5/5 frozen holdout scenarios
- zero executed hard violations
- zero incomplete traces
- Golden Trace exact replay

## Next gate

1. Apply the reviewed patch to the exact frozen v0.4.2 commit.
2. Run `scripts/verify_v043.sh` without any cloud credentials.
3. Commit and push the implementation on the target branch.
4. Review the exact commit and diff.
5. Freeze a separate v0.4.3 cloud experiment protocol.
6. Run no real API until that review is complete.

Do not merge `main` and do not rerun v0.4.2.
