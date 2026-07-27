# v0.7 Memory Versioning Kernel — Status Baseline

**Frozen at:** a4191c1f09e11ce49a5bcd334c031cc2e764b8a2
**Tag:** v0.7-kernel-freeze

## Test counts

| Suite | Count | Status |
|-------|-------|--------|
| v0.7 memory contracts + invariants | 62 | PASS |
| v0.6 legacy regression | 159 | PASS |
| **Total** | **221** | **PASS** |

## Key digests

| Artifact | Digest |
|----------|--------|
| Golden Trace SHA-256 | c9f5606f37b01a1dc5fe65e0171d66e00a9e447eed7cb728e072a9cabde3159d |
| Golden state digest | f46dccab2257b789ea7ca05e11288348e6e33daf5f32d135ac30e039f7a516ee |
| Golden occurrence digest | 13244a8b76a05e410d5c3d235394abf8c93c1c6a16f51a5c63e82b8884d31d1a |
| T20 final state digest | 51ebdce5187f7dfdd06a6b196f5b4324b9908ece5a67c6cba07c0ba382f5f2db |
| T20 replay digest | 51ebdce5187f7dfdd06a6b196f5b4324b9908ece5a67c6cba07c0ba382f5f2db |

## T20 stress constraints

| Constraint | Result |
|------------|--------|
| Transitions | 10,000 |
| Lineage cycles | 0 |
| Partial commits | 0 |
| Digest mismatches | 0 |
| Max live name records | 130 |
| Max live connection versions | 129 |
| Max recent archive references | 256 |
| Active lineage bound (256) | PASS |
| Versions per lineage bound (4) | PASS |
| Forgetting cache bound (256) | PASS |
| Ack cache bound (128) | PASS |
| Query cache bound (128) | PASS |
| Manifestation audit bound (128) | PASS |
