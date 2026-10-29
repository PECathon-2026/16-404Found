"""Event bus: persist to `audit_events` first (source of truth, SSE cursor), then fan out to live subscribers."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from ..common.ids import new_id, now_iso
from ..db import Database, audit_events


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def publish(self, mission_id: str, type_: str, actor: str, payload: dict[str, Any] | None = None,
                task_id: str | None = None) -> dict[str, Any]:
        evt = {
            "id": new_id("evt"), "mission_id": mission_id, "type": type_, "actor": actor, "task_id": task_id,
            "payload": payload or {}, "created_at": now_iso(),
        }
        self.db.insert(audit_events, **evt)
        for q in list(self._subs[mission_id]):
            q.put_nowait(evt)
        return evt

    def subscribe(self, mission_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs[mission_id].add(q)
        return q

    def unsubscribe(self, mission_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs[mission_id].discard(q)

    def history(self, mission_id: str, after_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        extra = audit_events.c.id > after_id if after_id else None
        rows = self.db.select(audit_events, order_by="id", where_cols={"mission_id": mission_id}, extra=extra, limit=limit)
        return rows
