# FX4 Notes (Hidden)

## Planted Security Vulnerabilities
1. **SQL Injection (CWE-89)** in `notes_api/notes.py`:
   `search_notes(term)`:
   `f"SELECT id, title, content FROM notes WHERE content LIKE '%{term}%'"`
   Must be converted to parameterized SQL query:
   `cur.execute("SELECT id, title, content FROM notes WHERE content LIKE ? LIMIT ?", (f"%{term}%", limit))`
2. **Hardcoded Secret Key (CWE-798)** in `notes_api/config.py`:
   `API_TOKEN = "sk-live-9876543210abcdef0123456789abcdef"`
   Should be loaded from environment variables or secrets manager.
3. **Command Injection / Insecure Subprocess (CWE-78)** in `notes_api/notes.py`:
   `export_note(note_id, target_path)` calls `subprocess.run(f"cat {target_path}", shell=True)`.
   Must avoid `shell=True` and validate filesystem paths.
