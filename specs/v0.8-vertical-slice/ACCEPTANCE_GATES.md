# v0.8 Acceptance Gates

## Gate A — repository

- `python -m compileall -q src tests tools`
- `pytest -q`
- `python tools/run_v080_text_slice.py --demo`
- `git diff --check`

Expected additions: 7 slice tests. Existing v0.7 behavior remains unchanged.

## Gate B — service

- `/health` succeeds;
- create session succeeds;
- canonical 11-command script reaches `COMPLETE`;
- duplicate `action_id` is idempotent;
- tampered save digest is rejected;
- server restart + load restores the same state.

## Gate C — UE body

- Qingyan moves to the front-door listen point 20/20 times without crossing collision;
- disconnect does not repeat an accepted command;
- `NO_PATH`, `TIMEOUT` and `INTERRUPTED` are visibly reported;
- Day-2 manifestation is visibly different for at least two Night-1 choices;
- save/load after Night 1 and after Day 2 restores matching state.

## Gate D — player comprehension

With no developer explanation, at least 3 of 5 testers correctly answer:

1. What did you record?
2. Why did the room/NPC change?
3. Which past event did the record not erase?

Failure at Gate D means revise presentation and pacing, not the v0.7 kernel.
