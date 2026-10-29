"""Notes management business logic with planted vulnerabilities for review testing."""

import subprocess
from typing import Any, Dict, List

from notes_api.db import get_connection


def add_note(title: str, content: str) -> int:
    """Adds a new note safely using parameterized queries."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO notes (title, content) VALUES (?, ?)", (title, content))
    conn.commit()
    return cur.lastrowid or 0


def search_notes(term: str) -> List[Dict[str, Any]]:
    """Searches notes by keyword in content.

    Planted vulnerability (CWE-89): SQL injection via f-string formatting.
    """
    conn = get_connection()
    cur = conn.cursor()
    # Planted SQL injection:
    query = f"SELECT id, title, content FROM notes WHERE content LIKE '%{term}%'"
    cur.execute(query)
    rows = cur.fetchall()
    return [{"id": row["id"], "title": row["title"], "content": row["content"]} for row in rows]


def export_note(note_id: int, target_path: str) -> str:
    """Exports a note to disk and verifies via subprocess.

    Planted vulnerability (CWE-78): Command injection via shell=True.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT content FROM notes WHERE id = ?", (note_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Note {note_id} not found")

    content = row["content"]
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Planted shell=True command execution:
    subprocess.run(f"cat {target_path}", shell=True, capture_output=True, text=True)
    return content
