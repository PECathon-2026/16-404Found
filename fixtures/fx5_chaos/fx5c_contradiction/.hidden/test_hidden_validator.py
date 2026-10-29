"""Hidden grading tests for validator."""

from validator.core import validate_token


def test_hidden_empty() -> None:
    assert validate_token("") is False


def test_hidden_special_characters() -> None:
    assert validate_token("token!@#") is False
