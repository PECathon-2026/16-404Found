"""State Manager: the single write path for mission state (AGENTS.md §D). Validates, versions, emits events."""
from __future__ import annotations

from typing import Any

from ..common.ids import new_id, now_iso
from ..db import (
    Database,
    acceptance_criteria,
    agent_messages,
    approvals,
    checkpoints,
    code_changes,
    decisions,
    human_requests,
    missions,
    security_findings,
    task_dependencies,
    tasks,
    test_runs,
    tool_calls,
    verification_reports,
)
from ..events.bus import EventBus
from .enums import EVENT_TYPES, MessageType, MissionStatus, Severity, TaskStatus
from .transitions import IllegalTransition, assert_transition, is_terminal

NEEDS_EVIDENCE = {MessageType.FINDING, MessageType.CRITIQUE, MessageType.TASK_RESULT}


class StateError(Exception):
    pass


class StateManager:
    def __init__(self, db: Database, bus: EventBus):
        self.db, self.bus = db, bus

    # ---- missions
    def create_mission(self, repository_id: str, title: str, request: str, config: dict[str, Any], mode: str) -> dict[str, Any]:
        mid = new_id("mis")
        now = now_iso()
        row = self.db.insert(
            missions, id=mid, repository_id=repository_id, title=title, request=request, status=MissionStatus.CREATED,
            status_before_pause=None, status_reason=None, config=config, criteria_version=1, current_patch_sha256=None,
            state_version=1, repair_cycles=0, replans=0, steps=0, tokens_used=0, cost_used_usd=0.0, workspace_path=None,
            base_commit=None, baseline_run_id=None, mode=mode, outcome=None, plan_summary=None, created_at=now,
            updated_at=now, finished_at=None,
        )
        self.bus.publish(mid, "mission.created", "system", {"title": title, "repository_id": repository_id, "mode": mode})
        return row

    def mission(self, mid: str) -> dict[str, Any]:
        m = self.db.get(missions, mid)
        if not m:
            raise StateError(f"mission {mid} not found")
        return m

    def update_mission(self, mid: str, **values: Any) -> None:
        m = self.mission(mid)
        self.db.update(missions, mid, state_version=(m["state_version"] or 0) + 1, updated_at=now_iso(), **values)

    def bump(self, mid: str, field: str, n: int = 1) -> int:
        m = self.mission(mid)
        new = (m[field] or 0) + n
        self.update_mission(mid, **{field: new})
        return new

    def set_status(self, mid: str, to: MissionStatus, reason: str | None = None, actor: str = "master") -> None:
        m = self.mission(mid)
        src = MissionStatus(m["status"])
        if src == to:
            return
        assert_transition(src, to)
        extra: dict[str, Any] = {"status_reason": reason}
        if to == MissionStatus.PAUSED:
            extra["status_before_pause"] = src
        if is_terminal(to):
            extra["finished_at"] = now_iso()
        self.update_mission(mid, status=to, **extra)
        self.checkpoint(mid, "STATE", str(to))
        self.bus.publish(mid, "mission.status_changed", actor, {"from": str(src), "to": str(to), "reason": reason})

    def checkpoint(self, mid: str, kind: str, status: str, patch_sha: str | None = None, git_ref: str | None = None) -> str:
        m = self.mission(mid)
        cid = new_id("ckp")
        self.db.insert(checkpoints, id=cid, mission_id=mid, kind=kind, status=status, state_version=m["state_version"],
                       patch_sha256=patch_sha, git_ref=git_ref, created_at=now_iso())
        return cid

    # ---- tasks
    def add_task(self, mid: str, kind: str, title: str, description: str = "", files_hint: list[str] | None = None,
                 criteria_refs: list[str] | None = None, depends_on: list[str] | None = None, max_retries: int = 3,
                 plan_version: int = 1, failure_context: dict[str, Any] | None = None) -> dict[str, Any]:
        n = len(self.db.select(tasks, where_cols={"mission_id": mid})) + 1
        tid = new_id("tsk")
        now = now_iso()
        row = self.db.insert(
            tasks, id=tid, mission_id=mid, key=f"TASK-{n}", kind=kind, title=title, description=description,
            status=TaskStatus.PENDING, assignee_agent=None, retries=0, max_retries=max_retries, files_hint=files_hint or [],
            criteria_refs=criteria_refs or [], failure_fingerprints=[], failure_context=failure_context,
            superseded_by=None, plan_version=plan_version, created_at=now, updated_at=now, started_at=None, finished_at=None,
        )
        for d in depends_on or []:
            self.db.insert(task_dependencies, task_id=tid, depends_on_task_id=d)
        self.bus.publish(mid, "task.created", "master", {"task_id": tid, "key": row["key"], "kind": kind, "title": title,
                                                       "depends_on": depends_on or []}, task_id=tid)
        return row

    def task(self, tid: str) -> dict[str, Any]:
        t = self.db.get(tasks, tid)
        if not t:
            raise StateError(f"task {tid} not found")
        return t

    def tasks(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(tasks, order_by="created_at", where_cols={"mission_id": mid})

    def dependencies(self, mid: str) -> list[tuple[str, str]]:
        ids = {t["id"] for t in self.tasks(mid)}
        return [(d["task_id"], d["depends_on_task_id"]) for d in self.db.select(task_dependencies) if d["task_id"] in ids]

    def set_task_status(self, tid: str, to: TaskStatus, actor: str = "master", **extra: Any) -> None:
        t = self.task(tid)
        if t["status"] == to and not extra:
            return
        vals: dict[str, Any] = {"status": to, "updated_at": now_iso(), **extra}
        if to == TaskStatus.IN_PROGRESS and not t["started_at"]:
            vals["started_at"] = now_iso()
        if to in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SUPERSEDED):
            vals["finished_at"] = now_iso()
        self.db.update(tasks, tid, **vals)
        self.bus.publish(t["mission_id"], "task.status_changed", actor,
                         {"task_id": tid, "key": t["key"], "from": t["status"], "to": str(to)}, task_id=tid)

    def promote_ready(self, mid: str) -> list[dict[str, Any]]:
        """PENDING tasks whose dependencies are all DONE become READY."""
        ts = {t["id"]: t for t in self.tasks(mid)}
        deps = self.dependencies(mid)
        out = []
        for t in ts.values():
            if t["status"] != TaskStatus.PENDING:
                continue
            mine = [d for (a, d) in deps if a == t["id"]]
            if all(ts[d]["status"] in (TaskStatus.DONE, TaskStatus.SUPERSEDED) for d in mine if d in ts):
                self.set_task_status(t["id"], TaskStatus.READY)
                out.append(self.task(t["id"]))
        return out

    # ---- criteria
    def set_criteria(self, mid: str, items: list[dict[str, Any]], version: int) -> None:
        self.db.delete_where(acceptance_criteria, mission_id=mid)
        for i, it in enumerate(items, 1):
            self.db.insert(acceptance_criteria, id=new_id("acr"), mission_id=mid, ac_key=it.get("id") or f"AC-{i}",
                           text=it["text"], verification=it.get("verification") or {"method": "manual_review"},
                           status="UNVERIFIED", evidence_refs=[], criteria_version=version)
        self.update_mission(mid, criteria_version=version)

    def criteria(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(acceptance_criteria, order_by="ac_key", where_cols={"mission_id": mid})

    def set_criterion_status(self, mid: str, ac_key: str, status: str, evidence_refs: list[Any]) -> None:
        with self.db.engine.begin() as c:
            c.execute(acceptance_criteria.update().where(
                (acceptance_criteria.c.mission_id == mid) & (acceptance_criteria.c.ac_key == ac_key)
            ).values(status=status, evidence_refs=evidence_refs))

    # ---- decisions / messages
    def record_decision(self, mid: str, step: int, action: str, rationale: str, forced_by: str, target_task_id: str | None = None,
                        target_agent: str | None = None, evidence_refs: list[Any] | None = None) -> dict[str, Any]:
        row = self.db.insert(decisions, id=new_id("dec"), mission_id=mid, step=step, action=action, target_task_id=target_task_id,
                             target_agent=target_agent, rationale=rationale, evidence_refs=evidence_refs or [], forced_by=forced_by,
                             created_at=now_iso())
        self.bus.publish(mid, "decision.made", "master", {"decision_id": row["id"], "action": action, "target_task_id": target_task_id,
                                                        "target_agent": target_agent, "rationale": rationale, "forced_by": forced_by})
        return row

    def post_message(self, mid: str, sender: str, recipient: str, type_: MessageType, payload: dict[str, Any],
                     evidence_refs: list[dict[str, Any]] | None = None, task_id: str | None = None,
                     correlation_id: str | None = None, in_reply_to: str | None = None,
                     severity: Severity = Severity.INFO, idempotency_key: str | None = None, attempt: int = 1,
                     ack_required: bool = False) -> dict[str, Any]:
        evidence_refs = evidence_refs or []
        if type_ in NEEDS_EVIDENCE and not evidence_refs:
            raise StateError(f"{type_} messages must carry evidence_refs")
        mine = new_id("msg")
        key = idempotency_key or f"{mid}:{task_id}:{type_}:{sender}:{mine}"
        existing = self.db.select(agent_messages, where_cols={"mission_id": mid, "idempotency_key": key})
        if existing:
            return {**existing[0], "duplicate": True}
        row = self.db.insert(
            agent_messages, id=mine, mission_id=mid, task_id=task_id, correlation_id=correlation_id or mine,
            in_reply_to=in_reply_to, sender=sender, recipient=recipient, type=type_, severity=severity, payload=payload,
            evidence_refs=evidence_refs, retry_attempt=attempt, idempotency_key=key,
            ack_status="PENDING" if ack_required else "N/A", duplicate_of=None, created_at=now_iso(),
        )
        self.bus.publish(mid, "message.sent", sender, {
            "message_id": mine, "sender": sender, "recipient": recipient, "type": str(type_), "severity": str(severity),
            "correlation_id": row["correlation_id"], "summary": str(payload.get("summary") or payload.get("title") or "")[:200],
        }, task_id=task_id)
        return row

    def ack(self, message_id: str) -> None:
        self.db.update(agent_messages, message_id, ack_status="ACKED")

    def messages(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(agent_messages, order_by="id", where_cols={"mission_id": mid})

    # ---- findings
    def add_finding(self, mid: str, raised_by: str, severity: Severity, category: str, file: str | None, line_start: int | None,
                    line_end: int | None, evidence: str, recommendation: str, confidence: float, fingerprint: str,
                    patch_sha: str | None, evidence_ref: dict[str, Any] | None, source: str, cwe: str | None = None,
                    task_id: str | None = None) -> dict[str, Any]:
        now = now_iso()
        row = self.db.insert(
            security_findings, id=new_id("fnd"), mission_id=mid, task_id=task_id, raised_by=raised_by, severity=severity,
            category=category, cwe=cwe, file=file, line_start=line_start, line_end=line_end, evidence=evidence,
            evidence_ref=evidence_ref, recommendation=recommendation, confidence=confidence, status="OPEN",
            fingerprint=fingerprint, first_patch_sha256=patch_sha, resolved_patch_sha256=None, waive_reason=None,
            source=source, created_at=now, updated_at=now,
        )
        self.bus.publish(mid, "finding.created", raised_by, {"finding_id": row["id"], "severity": str(severity),
                         "category": category, "file": file, "line_start": line_start, "status": "OPEN"}, task_id=task_id)
        return row

    def findings(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(security_findings, order_by="created_at", where_cols={"mission_id": mid})

    def set_finding_status(self, fid: str, status: str, patch_sha: str | None = None, reason: str | None = None, actor: str = "security") -> None:
        f = self.db.get(security_findings, fid)
        if not f:
            raise StateError("finding not found")
        vals: dict[str, Any] = {"status": status, "updated_at": now_iso()}
        if status == "RESOLVED":
            vals["resolved_patch_sha256"] = patch_sha
        if reason:
            vals["waive_reason"] = reason
        self.db.update(security_findings, fid, **vals)
        if status in ("RESOLVED", "WAIVED_BY_HUMAN", "WONT_FIX_EVIDENCED"):
            self.bus.publish(f["mission_id"], "finding.resolved", actor, {"finding_id": fid, "severity": f["severity"],
                             "category": f["category"], "file": f["file"], "line_start": f["line_start"], "status": status})

    # ---- misc reads
    def test_runs(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(test_runs, order_by="created_at", where_cols={"mission_id": mid})

    def tool_calls(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(tool_calls, order_by="started_at", where_cols={"mission_id": mid})

    def code_changes(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(code_changes, order_by="created_at", where_cols={"mission_id": mid})

    def latest_verification(self, mid: str) -> dict[str, Any] | None:
        rows = self.db.select(verification_reports, order_by="started_at", where_cols={"mission_id": mid})
        return rows[-1] if rows else None

    def approvals(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(approvals, order_by="requested_at", where_cols={"mission_id": mid})

    def human_requests(self, mid: str) -> list[dict[str, Any]]:
        return self.db.select(human_requests, order_by="created_at", where_cols={"mission_id": mid})


__all__ = ["StateManager", "StateError", "IllegalTransition", "EVENT_TYPES"]
