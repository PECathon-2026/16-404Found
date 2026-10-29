"""Security repo - SQL string building and hardcoded password."""


# WARNING: Demo repo with deliberate security flaws. Never do this in real code.
DB_PASSWORD = "admin123"  # BUG: hardcoded password


def get_user(conn, username: str) -> dict:
    """Get user from DB - SECURITY BUG: SQL injection via string building."""
    # BUG: string-built SQL is vulnerable to injection
    query = "SELECT * FROM users WHERE username = '" + username + "'"
    cursor = conn.cursor()
    cursor.execute(query)
    return cursor.fetchone()


def add_user(conn, username: str, email: str) -> None:
    """Add a user to the DB - SECURITY BUG: SQL injection."""
    query = "INSERT INTO users (username, email) VALUES ('" + username + "', '" + email + "')"
    cursor = conn.cursor()
    cursor.execute(query)
    conn.commit()


def safe_function(x: int, y: int) -> int:
    """A safe function with no security issues."""
    return x + y
