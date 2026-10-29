"""Persistent per-repository memory (bonus B-3): short lessons from COMPLETED missions, recalled as *hints* for later
missions on the same repository. Never presented as verified fact."""
from __future__ import annotations

from ..common.ids import new_id, now_iso
from ..db import agent_executions, memory_entries
from ..deps import Deps


def remember(deps: Deps, mission_id: str) -> int:
    m = deps.state.mission(mission_id)
    n = 0
    for e in deps.db.select(agent_executions, order_by="started_at", where_cols={"mission_id": mission_id, "agent_id": "developer"}):
        r = e["result"] or {}
        if e["status"] == "OK" and r.get("summary"):
            deps.db.insert(memory_entries, id=new_id("mem"), repository_id=m["repository_id"], kind="lesson",
                           text=f"{m['title']}: {r['summary'][:240]}", files=r.get("files_changed", []), source_mission_id=mission_id, created_at=now_iso())
            n += 1
    ps = m["plan_summary"] or {}
    if ps.get("conventions") and not deps.db.select(memory_entries, where_cols={"repository_id": m["repository_id"], "kind": "conventions"}):
        deps.db.insert(memory_entries, id=new_id("mem"), repository_id=m["repository_id"], kind="conventions", text=f"detected conventions: {ps['conventions']}",
                       files=[], source_mission_id=mission_id, created_at=now_iso())
        n += 1
    return n


def recall(deps: Deps, repository_id: str, limit: int = 5) -> list[str]:
    rows = deps.db.select(memory_entries, order_by="created_at", desc=True, where_cols={"repository_id": repository_id}, limit=limit)
    return [r["text"] for r in rows]
