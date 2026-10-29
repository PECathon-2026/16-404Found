"""mission.* tools: the narrow, validated write path agents use for shared state (T5.08)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..common.scanners import fingerprint
from ..state.enums import MessageType, Severity, TaskStatus
from .base import ToolContext, ToolError, ToolSpec


def digest(ctx: ToolContext) -> dict[str, Any]:
    s = ctx.deps.state
    m = s.mission(ctx.mission_id)
    runs = s.test_runs(ctx.mission_id)
    return {
        "status": m["status"], "criteria": [{"id": c["ac_key"], "text": c["text"], "status": c["status"]} for c in s.criteria(ctx.mission_id)],
        "tasks": [{"id": t["id"], "key": t["key"], "kind": t["kind"], "status": t["status"], "title": t["title"]} for t in s.tasks(ctx.mission_id)],
        "open_findings": [{"id": f["id"], "severity": f["severity"], "category": f["category"], "file": f["file"], "line": f["line_start"]}
                          for f in s.findings(ctx.mission_id) if f["status"] in ("OPEN", "DISPUTED", "FIX_PROPOSED")],
        "latest_test_run": ({k: runs[-1][k] for k in ("id", "kind", "outcome", "total", "passed", "failed")} if runs else None),
        "current_patch_sha256": m["current_patch_sha256"],
    }


class GetStateArgs(BaseModel):
    pass


async def get_state(ctx: ToolContext, a: GetStateArgs) -> dict:
    return digest(ctx)


class PostArgs(BaseModel):
    recipient: str
    type: MessageType
    summary: str
    payload: dict[str, Any] = {}
    evidence_refs: list[dict[str, Any]] = []
    in_reply_to: str | None = None
    severity: Severity = Severity.INFO


async def post_message(ctx: ToolContext, a: PostArgs) -> dict:
    try:
        row = ctx.deps.state.post_message(ctx.mission_id, ctx.agent_id, a.recipient, a.type, {"summary": a.summary, **a.payload},
                                          a.evidence_refs, ctx.task_id, in_reply_to=a.in_reply_to, severity=a.severity)
    except Exception as e:  # noqa: BLE001
        raise ToolError("INVALID_ARGS", str(e)) from None
    return {"message_id": row["id"]}


class FindingArgs(BaseModel):
    severity: Severity
    category: str
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    evidence: str
    recommendation: str
    confidence: float = 0.6
    evidence_refs: list[dict[str, Any]] = []


async def record_finding(ctx: ToolContext, a: FindingArgs) -> dict:
    if not a.evidence_refs and not a.evidence:
        raise ToolError("INVALID_ARGS", "findings need evidence")
    fp = fingerprint(a.category, a.file or "", a.evidence)
    f = ctx.deps.state.add_finding(
        ctx.mission_id, ctx.agent_id, a.severity, a.category, a.file, a.line_start, a.line_end, a.evidence[:600], a.recommendation,
        a.confidence, fp, ctx.deps.state.mission(ctx.mission_id)["current_patch_sha256"],
        (a.evidence_refs or [{"kind": "tool_call", "id": ctx.current_tcl}])[0], f"agent:{ctx.agent_id}", task_id=ctx.task_id)
    return {"finding_id": f["id"]}


class UpdateTaskArgs(BaseModel):
    status: TaskStatus
    note: str = ""


async def update_task(ctx: ToolContext, a: UpdateTaskArgs) -> dict:
    if ctx.agent_id != "master" and a.status not in (TaskStatus.IN_REVIEW, TaskStatus.BLOCKED):
        raise ToolError("POLICY_DENIED", "agents may only move their own task to IN_REVIEW or BLOCKED")
    if not ctx.task_id:
        raise ToolError("INVALID_ARGS", "no task in context")
    ctx.deps.state.set_task_status(ctx.task_id, a.status, actor=ctx.agent_id)
    return {"task_id": ctx.task_id, "status": str(a.status)}


SPECS = [
    ToolSpec("mission.get_state", "Get a digest of the shared mission state.", GetStateArgs, get_state),
    ToolSpec("mission.post_message", "Send a typed message to another agent (FINDING/CRITIQUE/TASK_RESULT need evidence_refs).", PostArgs, post_message),
    ToolSpec("mission.record_finding", "Record a finding with evidence.", FindingArgs, record_finding),
    ToolSpec("mission.update_task", "Move your own task to IN_REVIEW or BLOCKED.", UpdateTaskArgs, update_task),
]
