"""Hidden grading tests for median calculation."""

import pytest
import calc_stats.stats as s


def test_hidden_odd_length_median() -> None:
    assert hasattr(s, "median"), "stats module must export median function"
    assert s.median([1, 5, 2]) == 2.0  # type: ignore[attr-defined]


def test_hidden_even_length_median() -> None:
    assert hasattr(s, "median")
    assert s.median([1, 2, 3, 4]) == 2.5  # type: ignore[attr-defined]


def test_hidden_empty_median_raises() -> None:
    assert hasattr(s, "median")
    with pytest.raises(ValueError):
        s.median([])  # type: ignore[attr-defined]
