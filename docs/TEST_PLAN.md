# Deterministic Core Test Plan v0.3.1

| # | Scenario | Primary layer |
|---:|---|---|
| 1 | Normal observe and source-qualified report | Full loop |
| 2 | Explicit no-open constraint | Gateway |
| 3 | Player cancellation | Task state |
| 4 | Missing target | Gateway / grounding |
| 5 | Blocked path recovery | Executor feedback |
| 6 | Locked door | Preconditions |
| 7 | Unseen name not fabricated | Knowledge boundary |
| 8 | Prompt injection treated as data | Hard constraint |
| 9 | Forgotten name excluded from context | Memory access |
| 10 | Emotion survives without forgotten fact | Memory access |
| 11 | Conflicting witnesses preserved | Belief/source boundary |
| 12 | Timeout retry and recovery | ActionResult feedback |
| 13 | Repeated identical error stops | Loop guard |
| 14 | Self-harm request refused | Intent/role boundary |
| 15 | Casual chat triggers no world action | Intent routing |
| 16 | Explicit delegation enters task loop | Intent routing |
| 17 | Terminal task rejects more ticks | Task state |
| 18 | Save/load snapshot remains consistent | Persistence contract |
| 19 | Rewrite seals old memory | Memory version access |
| 20 | Five-step cap returns explained failure | Evaluator |

A scenario is considered passing when its expected terminal state, reason codes, context inclusion/exclusion rules, world state and Trace completeness all match. A scenario may intentionally end in `failed` or `cancelled`; the harness passes it only when that is the specified outcome.
