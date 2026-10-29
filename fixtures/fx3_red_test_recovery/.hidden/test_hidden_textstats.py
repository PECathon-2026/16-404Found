"""Hidden grading tests for FX3 whitespace normalization."""

from textstats.stats import word_count, word_freq


def test_hidden_tabs() -> None:
    counts = word_freq("hello\tworld\tagain")
    assert counts == {"hello": 1, "world": 1, "again": 1}


def test_hidden_mixed_whitespace() -> None:
    counts = word_freq("alpha \t\n beta \n\n gamma")
    assert counts == {"alpha": 1, "beta": 1, "gamma": 1}
    assert "" not in counts


def test_hidden_leading_trailing_spaces() -> None:
    counts = word_freq("   padded text   ")
    assert counts == {"padded": 1, "text": 1}
    assert "" not in counts


def test_hidden_word_count_with_whitespace() -> None:
    assert word_count("one   two   three") == 3
    assert word_count("line1\nline2\nline3") == 3


def test_hidden_punctuation_preserved() -> None:
    counts = word_freq("hello! world?")
    assert "hello!" in counts
    assert "world?" in counts
