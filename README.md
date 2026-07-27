# WangSheng Agent Lab

Reliability-first framework for AI-controlled game NPCs.

## v0.7 Memory Versioning Kernel (P0–P5 deterministic freeze)

The v0.7 Memory Versioning Kernel implements a strict bounded, deterministic, append-only memory system for AI game NPCs. The kernel is validated entirely without LLM calls (P0–P5 deterministic only). Real-model acceptance (P6) is pending.

### Core architecture

- **Occurrence** — immutable append-only events with Canonical JSON SHA-256 digest
- **Observation** — typed perception (OBSERVED / HEARD / INFERRED / MANIFESTED) with role-private isolation and knowledge-leak rejection
- **Memory** — versioned belief records with lineage tracking, clarity/emotion state snapshots, and structured forgetting events
- **NameRecord** — draft acknowledgement protocol with permission levels (WITNESS / BELONGING / LIMITED_CONTINUITY)
- **Conflict** — four typed conflict classes (logical mutual exclusion, physical exclusive occupancy, institutional exclusive occupancy, declared capacity competition)
- **Acknowledgement** — atomic WorldAcknowledgement + ConnectionVersion + ManifestationDelta transactions against an append-only authoritative Trace
- **Replay** — full deterministic state reconstruction from Canonical JSON archives with SHA-256 integrity verification

### T01–T20 contract results

| Test | Status | Description |
|------|--------|-------------|
| T01–T08 | PASS | Occurrence / Observation / Memory core (P2) |
| T09–T16 | PASS | Forgetting / Records / Typed conflicts (P3) |
| T17–T19 | PASS | Acknowledgement / Manifestation / Save-load-replay (P4) |
| T20 | PASS | Same-world 10,000-transition bounded stress (P5) |

### Verification

```bash
# Full deterministic suite
PYTHONPATH=src python -m pytest -q
# Expected: 221 passed

# Memory-specific
PYTHONPATH=src python -m pytest tests/memory -q
# Expected: 62 passed

# P5 verifier
PYTHONPATH=src python scripts/verify_v070_p5.py
# Expected: status = PASS
```

### Golden Trace

- File: `golden_traces/v070_xiaoman_three_day.jsonl`
- Records: 16
- SHA-256: `c9f5606f37b01a1dc5fe65e0171d66e00a9e447eed7cb728e072a9cabde3159d`
- State digest: `f46dccab2257b789ea7ca05e11288348e6e33daf5f32d135ac30e039f7a516ee`
- Occurrence digest: `13244a8b76a05e410d5c3d235394abf8c93c1c6a16f51a5c63e82b8884d31d1a`

### Evidence limits

v0.7 P0–P5 is a fully deterministic kernel freeze. It does not include:
- Real-model (LLM) acceptance — P6 pending
- UE5 integration
- Complete NameRecord gameplay
- Long-term multi-NPC narrative
- Verified model with reliable long-term memory

See:
- `docs/V0.7_KERNEL_FREEZE_REPORT.md`
- `docs/STATUS_BASELINE.md`
- `docs/REVIEW_STATUS.md`
