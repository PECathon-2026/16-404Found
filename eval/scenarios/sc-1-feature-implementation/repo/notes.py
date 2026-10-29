"""Simple note store."""

NOTES = [
    {"id": 1, "title": "Meeting notes", "body": "Discuss Q3 roadmap and milestones"},
    {"id": 2, "title": "Shopping list", "body": "Milk, coffee beans, sourdough bread"},
    {"id": 3, "title": "Project DevPilot", "body": "Multi-agent autonomous engineering guild"},
]


def get_all_notes():
    return list(NOTES)


def get_note_by_id(note_id):
    for n in NOTES:
        if n["id"] == note_id:
            return n
    return None

