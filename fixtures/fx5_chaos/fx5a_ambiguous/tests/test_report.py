import pytest
from repgen.report import generate_report


def test_empty_report() -> None:
    rep = generate_report([])
    assert rep["count"] == 0
    assert rep["mean"] == 0.0


def test_standard_report() -> None:
    rep = generate_report([10, 20, 30])
    assert rep["count"] == 3
    assert rep["mean"] == 20.0
    assert rep["sum"] == 60.0
