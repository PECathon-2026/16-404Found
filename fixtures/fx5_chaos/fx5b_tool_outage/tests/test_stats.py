import pytest
from calc_stats.stats import mean, total


def test_total() -> None:
    assert total([1, 2, 3, 4]) == 10.0
    assert total([]) == 0.0


def test_mean() -> None:
    assert mean([2, 4, 6]) == 4.0


def test_empty_mean_raises() -> None:
    with pytest.raises(ValueError):
        mean([])
