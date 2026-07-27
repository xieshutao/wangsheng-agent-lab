# v0.7 Memory Versioning Kernel — Review Status

**Freeze review:** 2026-07-27

## In scope (verified)

| Area | Status |
|------|--------|
| Occurrence append-only + immutable + SHA-256 digest | VERIFIED |
| Observation typing (OBSERVED / HEARD / INFERRED / MANIFESTED) | VERIFIED |
| Role-private observation isolation | VERIFIED |
| Knowledge-leak rejection | VERIFIED |
| Memory versioning + lineage | VERIFIED |
| Memory state snapshot separation | VERIFIED |
| Fact-only / full forgetting + ForgettingEvent audit | VERIFIED |
| Forgetting suppression + rewrite lineage | VERIFIED |
| NameRecord / acknowledgement draft protocol | VERIFIED |
| Permission levels (L1 WITNESS / L2 BELONGING / L3 LIMITED_CONTINUITY) | VERIFIED |
| Consent requirement (L2/L3) | VERIFIED |
| Four typed conflict classes | VERIFIED |
| Conflict mitigation requirement | VERIFIED |
| Anti-self-proof (manifestation cannot prove own parent) | VERIFIED |
| Source-family deduplication | VERIFIED |
| Atomic WorldAcknowledgement + ConnectionVersion + ManifestationDelta | VERIFIED |
| Day-1 branch matrix (4 branches, shared occurrence digest) | VERIFIED |
| Day-3 outcome matrix (4 outcomes, shared occurrence digest) | VERIFIED |
| Canonical JSON archive + SHA-256 integrity | VERIFIED |
| Save-load-replay deterministic state reconstruction (3 checkpoints) | VERIFIED |
| 10,000-transition bounded stress (0 failures) | VERIFIED |
| Golden Trace frozen (16 records) | VERIFIED |

## Not in scope (pending)

| Area | Status |
|------|--------|
| Real-model (LLM) acceptance | P6 PENDING |
| UE5 integration | NOT STARTED |
| Complete NameRecord gameplay | NOT STARTED |
| Multi-NPC long-term narrative | NOT STARTED |
| Model reliable long-term memory | NOT STARTED |
| Kernel core / game-specific layer separation | NOT STARTED |
