# Hermes v0.4.3 application and verification

Apply the reviewed v0.4.2-to-v0.4.3 patch only on the exact frozen base:

- branch: `feat/cloud-episode-runner-v0.4.2`
- commit: `bfa50599cfffd20ff7584f097585d1ac9a81960a`
- target branch: `feat/failure-aware-replanning-v0.4.3`

The external execution prompt supplies the final patch SHA-256. Stop on any mismatch.

This stage is deterministic only. Do not configure or call a cloud model. Run `scripts/verify_v043.sh`, commit the reviewed diff, push the target branch and return the full commit plus clean worktree status.
