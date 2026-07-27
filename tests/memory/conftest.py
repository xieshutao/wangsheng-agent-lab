from __future__ import annotations

from pathlib import Path

import pytest

from wangsheng.memory import MemoryVersioningKernel


@pytest.fixture
def kernel() -> MemoryVersioningKernel:
    return MemoryVersioningKernel()


@pytest.fixture
def xiaoman_fixture_path() -> Path:
    path = Path("specs/v0.7/scenarios/xiaoman_three_day_kernel_fixture_v0.7.json")
    assert path.is_file(), f"missing frozen v0.7 fixture: {path}"
    return path
