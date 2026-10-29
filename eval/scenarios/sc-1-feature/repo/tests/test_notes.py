from notes import get_note, list_notes


def test_list_notes_returns_all():
    assert len(list_notes()) == 3


def test_get_note_found():
    assert get_note(2)["title"] == "Call Ana"


def test_get_note_missing():
    assert get_note(99) is None
