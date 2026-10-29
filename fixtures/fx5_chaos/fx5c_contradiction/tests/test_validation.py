import pytest
from validator.core import validate_token


def test_standard_valid() -> None:
    assert validate_token("user123") is True


def test_too_short() -> None:
    assert validate_token("abc") is False


# Planted contradictory tests: cannot both pass simultaneously
def test_contradictory_requirement_a() -> None:
    assert validate_token("admin_secret") is True


def test_contradictory_requirement_b() -> None:
    assert validate_token("admin_secret") is False
