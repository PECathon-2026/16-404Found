"""Tiny notes store."""

NOTES = [
    {"id": 1, "title": "Buy milk", "body": "Two litres of whole milk"},
    {"id": 2, "title": "Call Ana", "body": "About the Quarterly report"},
    {"id": 3, "title": "Gym", "body": "Leg day"},
]


def list_notes():
    return list(NOTES)


def get_note(note_id):
    for n in NOTES:
        if n["id"] == note_id:
            return n
    return None
