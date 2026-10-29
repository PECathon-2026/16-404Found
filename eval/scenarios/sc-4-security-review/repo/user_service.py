"""User lookup service."""
import sqlite3


def get_connection():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT)")
    cur.execute("INSERT INTO users (id, email, name) VALUES (1, 'alice@example.com', 'Alice')")
    cur.execute("INSERT INTO users (id, email, name) VALUES (2, 'bob@example.com', 'Bob')")
    conn.commit()
    return conn

