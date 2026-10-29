"""Shared fixtures for state tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.state.event_store import JsonlEventStore


@pytest.fixture
def store(tmp_path: Path) -> JsonlEventStore:
    return JsonlEventStore(tmp_path / "runs")
