# WangSheng Agent Lab

Reliability-first framework for testing local-LLM-controlled game NPCs.

This baseline intentionally contains no language model, CUDA dependency, Unreal plugin,
model weights, or API keys. It first proves the deterministic control loop:

1. one player command creates one persistent task;
2. one tick accepts at most one action;
3. every action is checked before execution;
4. execution returns a structured observation;
5. the same task continues across ticks;
6. only the evaluator can mark the task complete.

## First scenario

The `door_visitor` scenario models:

> Confirm who is outside the front door, but do not open it. Return and report the result.

Reference sequence:

`move_to -> listen_at -> talk_to -> return_to -> report`

## Install and test

```bash
python -m pip install -e ".[dev]"
pytest -q
python -m wangsheng.cli demo-door
```

## Architecture

```text
Player command
  -> EpisodeEngine
  -> Policy proposes exactly one Action
  -> Gateway validates it
  -> Executor changes the simulated world
  -> structured Observation
  -> TaskEvaluator checks real completion criteria
  -> next tick
```
