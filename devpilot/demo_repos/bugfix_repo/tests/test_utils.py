"""Tests for bugfix_repo utils - includes a failing test."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import get_top_n, sum_list


def test_get_top_3():
    """get_top_n(items, 3) should return exactly 3 items."""
    result = get_top_n([5, 2, 8, 1, 9, 3], 3)
    assert len(result) == 3, f"Expected 3 items, got {len(result)}: {result}"


def test_get_top_n_values():
    """Top 3 from [5,2,8,1,9,3] should be [9,8,5]."""
    result = get_top_n([5, 2, 8, 1, 9, 3], 3)
    assert result == [9, 8, 5], f"Got: {result}"


def test_sum_list():
    """Sum works correctly."""
    assert sum_list([1, 2, 3]) == 6
