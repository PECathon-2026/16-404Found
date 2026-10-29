import pytest
from textstats.stats import char_count, word_count, word_freq


def test_char_count() -> None:
    assert char_count("hello") == 5
    assert char_count("") == 0


def test_simple_word_freq() -> None:
    counts = word_freq("apple banana apple")
    assert counts == {"apple": 2, "banana": 1}


def test_empty_string_freq() -> None:
    assert word_freq("") == {}


def test_case_insensitivity() -> None:
    counts = word_freq("Cat cat CAT")
    assert counts == {"cat": 3}


# The following two tests fail at baseline due to str.split(" ") refactor:


def test_multiple_spaces() -> None:
    counts = word_freq("hello   world")
    assert counts == {"hello": 1, "world": 1}
    assert "" not in counts


def test_newlines() -> None:
    counts = word_freq("hello\nworld")
    assert counts == {"hello": 1, "world": 1}
    assert "hello\nworld" not in counts
