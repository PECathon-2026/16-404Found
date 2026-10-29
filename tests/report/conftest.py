"""Fixtures for report tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fx2_support import Fx2, run_fx2


@pytest.fixture
async def fx2(tmp_path: Path) -> Fx2:
    return await run_fx2(tmp_path)
