"""Tests for stuck_repo - will always fail due to external dependency simulation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from solver import compute_answer


def test_compute_answer():
    """compute_answer must return exactly 42."""
    result = compute_answer()
    # This is intentionally hard to fix without understanding the domain
    assert result == 42, f"Expected 42, got {result}"
