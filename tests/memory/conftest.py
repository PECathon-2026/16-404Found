"""Fixtures for memory tests (reuses the FX2 scenario from tests/report)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "report"))

from fx2_support import Fx2, run_fx2


@pytest.fixture
async def fx2(tmp_path: Path) -> Fx2:
    return await run_fx2(tmp_path)
