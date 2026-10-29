"""User lookups."""
import sqlite3


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT)")
    conn.execute("INSERT INTO users (email, name) VALUES ('ana@example.com', 'Ana')")
    return conn


def get_user(conn, user_id):
    row = conn.execute("SELECT id, email, name FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(zip(("id", "email", "name"), row)) if row else None
