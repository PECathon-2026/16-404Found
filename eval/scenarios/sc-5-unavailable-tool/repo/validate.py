"""Input validation helpers."""


def validate_name(name):
    if not name or not name.strip():
        raise ValueError("name is required")
    return name.strip()
