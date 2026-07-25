# Architecture

## Core rule

The language model is never the source of world truth.

A policy proposes one action. The gateway validates it. The executor returns
the actual result. The evaluator decides whether the task is complete.

## Invariants

1. A submitted command remains the same active task until terminal.
2. At most one action is executed per tick.
3. Every attempted action produces one observation.
4. Rejected actions do not mutate the world.
5. `report` cannot complete a task unless all required evidence exists.
6. A terminal task cannot accept more actions.
