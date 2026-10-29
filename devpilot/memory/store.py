"""``SqliteMemoryStore``: ``ports.MemoryStore`` over stdlib ``sqlite3`` (run in a worker thread).

Recall ranks by bm25 (FTS5) or keyword overlap (LIKE fallback when this sqlite build has no FTS5),
multiplied by the item's confidence. Writes deduplicate on ``(repo_key, kind, normalised trigger)``.
A connection is opened per call, so the store is safe to use from several threads and processes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from devpilot.core.models import MemoryItem

_TOKEN = re.compile(r"[a-z0-9]+")
MAX_QUERY_TOKENS = 24
DEDUP_BOOST = 0.1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
  id TEXT PRIMARY KEY,
  repo_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('semantic','episodic','procedural')),
  "trigger" TEXT NOT NULL,
  trigger_norm TEXT NOT NULL,
  content TEXT NOT NULL,
  source_mission TEXT NOT NULL,
  evidence_ids TEXT NOT NULL DEFAULT '[]',
  confidence REAL NOT NULL DEFAULT 0.5,
  uses INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_used_at TEXT,
  last_validated TEXT,
  UNIQUE (repo_key, kind, trigger_norm)
);
CREATE INDEX IF NOT EXISTS ix_memory_repo ON memory (repo_key, kind);
"""
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  id UNINDEXED, trigger_text, content_text, tokenize = 'porter unicode61'
);
"""


def fts5_available() -> bool:
    """True when this sqlite build can create FTS5 tables."""
    try:
        with contextlib.closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.Error:
        return False


def normalise_trigger(trigger: str) -> str:
    return " ".join(trigger.lower().split())


def tokenise(text: str) -> list[str]:
    return list(dict.fromkeys(t for t in _TOKEN.findall(text.lower()) if len(t) >= 2))[:MAX_QUERY_TOKENS]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        repo_key=row["repo_key"],
        kind=cast(Literal["semantic", "episodic", "procedural"], row["kind"]),
        trigger=row["trigger"],
        content=row["content"],
        source_mission=row["source_mission"],
        evidence_ids=json.loads(row["evidence_ids"]),
        confidence=row["confidence"],
        uses=row["uses"],
        last_validated=datetime.fromisoformat(row["last_validated"]) if row["last_validated"] else None,
    )


class SqliteMemoryStore:
    """Persistent memory; ``use_fts=False`` forces the LIKE fallback (used by tests)."""

    def __init__(self, path: Path | str, *, use_fts: bool | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fts: bool = fts5_available() if use_fts is None else (use_fts and fts5_available())
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            if self.fts:
                existed = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'memory_fts'").fetchone()
                conn.executescript(_FTS_SCHEMA)
                if not existed:  # db created without FTS earlier: index what is already there
                    conn.execute(
                        "INSERT INTO memory_fts (id, trigger_text, content_text) "
                        'SELECT id, "trigger", content FROM memory'
                    )

    @contextlib.contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # one transaction: commit on success, roll back on error
                yield conn
        finally:
            conn.close()

    # ---- MemoryStore port -------------------------------------------------------------

    async def recall(self, repo_key: str, query: str, kinds: Sequence[str], k: int = 5) -> list[MemoryItem]:
        return await asyncio.to_thread(self._recall, repo_key, query, tuple(kinds), k)

    async def write(self, item: MemoryItem) -> None:
        await asyncio.to_thread(self._write, item)

    async def reinforce(self, item_id: str, delta: float) -> None:
        await asyncio.to_thread(self._reinforce, item_id, delta)

    # ---- extras (UI, tests) -------------------------------------------------------------

    async def get(self, item_id: str) -> MemoryItem | None:
        return await asyncio.to_thread(self._get, item_id)

    async def list_items(self, repo_key: str | None = None) -> list[MemoryItem]:
        return await asyncio.to_thread(self._list, repo_key)

    # ---- sync implementations -----------------------------------------------------------

    def _recall(self, repo_key: str, query: str, kinds: tuple[str, ...], k: int) -> list[MemoryItem]:
        if k <= 0 or not kinds:
            return []
        tokens = tokenise(query)
        marks = ",".join("?" for _ in kinds)
        with self._conn() as conn:
            scored: list[tuple[float, sqlite3.Row]]
            if not tokens:
                rows = conn.execute(
                    f"SELECT * FROM memory WHERE repo_key = ? AND kind IN ({marks})", (repo_key, *kinds)
                ).fetchall()
                scored = [(float(r["confidence"]), r) for r in rows]
            elif self.fts:
                match = " OR ".join(f'"{t}"' for t in tokens)
                rows = conn.execute(
                    "SELECT m.*, bm25(memory_fts, 0.0, 2.0, 1.0) AS rank FROM memory_fts "
                    "JOIN memory m ON m.id = memory_fts.id "
                    f"WHERE memory_fts MATCH ? AND m.repo_key = ? AND m.kind IN ({marks}) "
                    "ORDER BY rank LIMIT 200",
                    (match, repo_key, *kinds),
                ).fetchall()
                # bm25() is negative (more negative = better); flip it so higher is better
                scored = [(-float(r["rank"]) * float(r["confidence"]), r) for r in rows]
            else:
                likes = " OR ".join('lower("trigger") LIKE ? OR lower(content) LIKE ?' for _ in tokens)
                params: list[Any] = [repo_key, *kinds]
                for t in tokens:
                    params += [f"%{t}%", f"%{t}%"]
                rows = conn.execute(
                    f"SELECT * FROM memory WHERE repo_key = ? AND kind IN ({marks}) AND ({likes})", params
                ).fetchall()
                scored = []
                for r in rows:
                    have = set(_TOKEN.findall(f"{r['trigger']} {r['content']}".lower()))
                    hits = sum(1 for t in tokens if t in have or any(t in h for h in have))
                    scored.append((hits / len(tokens) * float(r["confidence"]), r))
            scored.sort(
                key=lambda s: (-s[0], -float(s[1]["confidence"]), -int(s[1]["uses"]), str(s[1]["id"]))
            )
            top = [r for _, r in scored[:k]]
            if top:
                ids = [r["id"] for r in top]
                conn.execute(
                    f"UPDATE memory SET uses = uses + 1, last_used_at = ? WHERE id IN ({','.join('?' for _ in ids)})",
                    (_now(), *ids),
                )
                top = conn.execute(
                    f"SELECT * FROM memory WHERE id IN ({','.join('?' for _ in ids)})", ids
                ).fetchall()
                order = {i: n for n, i in enumerate(ids)}
                top.sort(key=lambda r: order[r["id"]])
            return [_row_to_item(r) for r in top]

    def _write(self, item: MemoryItem) -> None:
        norm = normalise_trigger(item.trigger)
        now = _now()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM memory WHERE repo_key = ? AND kind = ? AND trigger_norm = ?",
                (item.repo_key, item.kind, norm),
            ).fetchone()
            if row is not None:
                merged = list(dict.fromkeys([*json.loads(row["evidence_ids"]), *item.evidence_ids]))
                conn.execute(
                    "UPDATE memory SET content = ?, evidence_ids = ?, source_mission = ?, "
                    "confidence = MIN(1.0, confidence + ?), last_validated = ? WHERE id = ?",
                    (item.content, json.dumps(merged), item.source_mission, DEDUP_BOOST, now, row["id"]),
                )
                self._reindex(conn, row["id"], item.trigger, item.content)
                return
            item_id = item.id
            if not item_id or conn.execute("SELECT 1 FROM memory WHERE id = ?", (item_id,)).fetchone():
                item_id = f"MEM-{uuid.uuid4().hex[:12]}"
            conn.execute(
                'INSERT INTO memory (id, repo_key, kind, "trigger", trigger_norm, content, source_mission, '
                "evidence_ids, confidence, uses, created_at, last_validated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    item.repo_key,
                    item.kind,
                    item.trigger,
                    norm,
                    item.content,
                    item.source_mission,
                    json.dumps(item.evidence_ids),
                    item.confidence,
                    item.uses,
                    item.created_at.isoformat(),
                    item.last_validated.isoformat() if item.last_validated else None,
                ),
            )
            self._reindex(conn, item_id, item.trigger, item.content)

    def _reindex(self, conn: sqlite3.Connection, item_id: str, trigger: str, content: str) -> None:
        if not self.fts:
            return
        conn.execute("DELETE FROM memory_fts WHERE id = ?", (item_id,))
        conn.execute(
            "INSERT INTO memory_fts (id, trigger_text, content_text) VALUES (?,?,?)",
            (item_id, trigger, content),
        )

    def _reinforce(self, item_id: str, delta: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE memory SET confidence = MIN(1.0, MAX(0.0, confidence + ?)) WHERE id = ?",
                (delta, item_id),
            )

    def _get(self, item_id: str) -> MemoryItem | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM memory WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row is not None else None

    def _list(self, repo_key: str | None) -> list[MemoryItem]:
        with self._conn() as conn:
            if repo_key is None:
                rows = conn.execute("SELECT * FROM memory ORDER BY created_at, id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE repo_key = ? ORDER BY created_at, id", (repo_key,)
                ).fetchall()
        return [_row_to_item(r) for r in rows]
