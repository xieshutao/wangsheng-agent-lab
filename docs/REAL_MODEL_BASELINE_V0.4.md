# Real-model baseline: DeepSeek V4 Pro on v0.4.0

## Source under test

```text
branch: feat/native-tool-calling-v0.4
commit: e88163f4f8c87118b743bef16236320b84a29720
model: deepseek-v4-pro
thinking: disabled
temperature: 0
```

Raw artifacts were intentionally kept outside Git. This document preserves the aggregate evidence used to justify v0.4.1.

## Configuration A: original 20×1

```text
tool_choice=auto
parallel_tool_calls field not sent
```

Results:

- run count: 20
- protocol valid: 11/20 (55%)
- semantic pass: 5/20 (25%)
- no tool call: 3
- multiple tool calls: 7
- provider-classified errors: 9
- selected forbidden tool: 0
- actual hard violation: 0
- mean latency: 2605 ms
- p95 latency: 4198 ms
- total tokens: 32089

Observed semantic patterns:

- preference for `listen_at` before moving near the door
- direct use of a canonical visitor ID that encoded identity
- task cases sometimes emitted no action
- several responses returned a future plan as parallel tool calls

## Configuration B: five-scenario control

```text
tool_choice=required
parallel_tool_calls=false
```

Results:

- protocol valid: 5/5 (100%)
- multiple tool calls: 0
- provider errors: 0
- semantic pass: 2/5 (40%)
- mean latency: 1533 ms
- p95 latency: 2037 ms
- total tokens: 7560

## Interpretation

Configuration B proved that the largest P0 failures were request-configuration defects rather than HTTP or parser failures. Remaining P1 failures were traced to model context and world-contract defects:

1. `available_actions` meant task-authorized tools, not currently executable tools;
2. proximity prerequisites were not explicit;
3. `visitor.xiaoman` leaked hidden identity through a target ID;
4. first-action semantic scoring did not require a Gateway-allowed action.

v0.4.1 changes only those general contracts. It does not add a model-specific answer key.
