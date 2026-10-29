"""Visible tests for notes_api."""

from pathlib import Path

import pytest
from notes_api.db import reset_db
from notes_api.notes import add_note, export_note, search_notes


@pytest.fixture(autouse=True)
def setup_db() -> None:
    reset_db()


def test_add_and_search_notes() -> None:
    id1 = add_note("Meeting", "Discuss project milestones")
    id2 = add_note("Shopping", "Buy groceries and coffee")

    results = search_notes("milestones")
    assert len(results) == 1
    assert results[0]["id"] == id1

    results_coffee = search_notes("coffee")
    assert len(results_coffee) == 1
    assert results_coffee[0]["id"] == id2


def test_search_notes_no_match() -> None:
    add_note("Note", "Simple test")
    results = search_notes("nonexistent")
    assert results == []


def test_export_note(tmp_path: Path) -> None:
    note_id = add_note("Export", "Note export content")
    out_file = tmp_path / "note.txt"
    content = export_note(note_id, str(out_file))
    assert content == "Note export content"
    assert out_file.read_text(encoding="utf-8") == "Note export content"
