#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${WANGSHENG_PYTHON:-${VIRTUAL_ENV:+${VIRTUAL_ENV}/bin/python}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONNOUSERSITE=1

cd "$PROJECT_ROOT"
"$PYTHON_BIN" -m pytest -q
"$PYTHON_BIN" -m py_compile \
  src/wangsheng/bridge/model_acceptance.py \
  tools/run_bridge_model_acceptance.py \
  tools/run_bridge_model_soak.py
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
from wangsheng.bridge.model_acceptance import discover_model_scenarios, load_model_scenario
paths = discover_model_scenarios(Path('scenarios_bridge_model_v060'))
assert len(paths) == 20, len(paths)
scenarios = [load_model_scenario(path) for path in paths]
assert len({item.scenario_id for item in scenarios}) == 20
assert {item.category for item in scenarios} == {'basic_async', 'fault_recovery', 'save_load_recovery'}
print({'scenario_count': 20, 'schema_check': 'passed'})
PY
