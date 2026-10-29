"""Statistical calculation functions."""

from typing import Sequence


def total(numbers: Sequence[float]) -> float:
    return float(sum(numbers))


def mean(numbers: Sequence[float]) -> float:
    if not numbers:
        raise ValueError("Cannot calculate mean of empty sequence")
    return float(sum(numbers) / len(numbers))
