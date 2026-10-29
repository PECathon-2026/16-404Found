"""Hidden grading tests for FX4 notes_api security and limit feature."""

import pytest
from notes_api.db import reset_db
from notes_api.notes import add_note, search_notes


@pytest.fixture(autouse=True)
def setup_db() -> None:
    reset_db()


def test_hidden_search_limit_parameter() -> None:
    """search_notes must accept limit parameter and cap returned items."""
    for i in range(10):
        add_note(f"Title {i}", f"Common keyword item {i}")

    # Must accept limit=3
    results = search_notes("Common", limit=3)  # type: ignore[call-arg]
    assert len(results) == 3


def test_hidden_search_default_limit() -> None:
    """Default limit must be 20 when more than 20 matching items exist."""
    for i in range(25):
        add_note(f"Note {i}", "Searchable body text")

    results = search_notes("Searchable")
    assert len(results) == 20


def test_hidden_sqli_payload_neutralized() -> None:
    """SQL injection payload must not retrieve unauthorized notes."""
    add_note("Secret", "Private confidential text")
    add_note("Public", "Public announcement")

    # SQL injection attempt
    payload = "' OR 1=1 --"
    try:
        results = search_notes(payload)
        # In a parameterized query searching for literal text, neither note matches
        assert len(results) == 0
    except Exception as exc:
        pytest.fail(f"SQL execution crashed on injection payload: {exc}")
