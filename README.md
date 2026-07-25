# WangSheng Agent Lab

Reliability-first framework for testing local-LLM-controlled game NPCs.

Version 0.2 adds a strict model contract without giving the model control over
world truth.

## Proven baseline

1. one player command creates one persistent task;
2. one tick accepts at most one action;
3. every action is checked before execution;
4. execution returns a structured observation;
5. the same task continues across ticks;
6. only the evaluator can mark the task complete;
7. model output must be exactly one strict JSON object;
8. malformed model output becomes a structured failed observation;
9. provider errors do not mutate the world;
10. OpenAI-compatible endpoints can be connected through a replaceable provider.

## First scenario

> Confirm who is outside the front door, but do not open it. Return and report.

Reference sequence:

`move_to -> listen_at -> talk_to -> return_to -> report`

## Install and test

```bash
python -m pip install -e ".[dev]"
pytest -q
python -m wangsheng.cli demo-door
python -m wangsheng.cli demo-model-contract
```

## Model output contract

The model must return only one compact JSON object:

```json
{"name":"move_to","target":"front_door","parameters":{}}
```

Rejected examples include Markdown fences, prose, arrays, unknown top-level
fields, missing action names, and non-object parameters.

## OpenAI-compatible provider

`OpenAICompatibleProvider` supports a normal `/v1/chat/completions` endpoint.
API keys are read from constructor arguments or `WANGSHENG_MODEL_API_KEY`; no
key is stored in the repository.

## Architecture

```text
Player command
  -> EpisodeEngine
  -> prompt builder
  -> model provider
  -> strict action parser
  -> exactly one Action
  -> Gateway validation
  -> Executor
  -> structured Observation
  -> TaskEvaluator
  -> next tick
```
