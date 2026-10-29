from notes import get_all_notes, get_note_by_id


def test_get_all():
    assert len(get_all_notes()) == 3


def test_get_by_id():
    n = get_note_by_id(1)
    assert n is not None
    assert n["title"] == "Meeting notes"


def test_get_by_id_missing():
    assert get_note_by_id(999) is None

