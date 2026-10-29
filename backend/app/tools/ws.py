"""Workspace operations shared by tools: patch computation and change recording."""
from __future__ import annotations

import hashlib

from ..common.ids import new_id, now_iso
from ..common.tamper import analyze_patch
from ..db import code_changes
from ..sandbox.git import git
from .base import ToolContext


async def compute_patch(ctx: ToolContext) -> tuple[str, str | None]:
    await git(ctx.workspace, "add", "-A")
    patch = await git(ctx.workspace, "diff", "--cached", "--binary", "--no-color", ctx.base_commit)
    sha = hashlib.sha256(patch.encode()).hexdigest() if patch.strip() else None
    return patch, sha


async def record_change(ctx: ToolContext, path: str, change_type: str) -> dict:
    patch, sha = await compute_patch(ctx)
    d = ctx.deps
    d.state.update_mission(ctx.mission_id, current_patch_sha256=sha)
    info = next((f for f in analyze_patch(patch)["files"] if f["path"] == path), None) or {
        "additions": 0, "deletions": 0, "is_test_file": False, "tamper_flags": [], "change_type": change_type}
    d.db.insert(code_changes, id=new_id("chg"), mission_id=ctx.mission_id, task_id=ctx.task_id, tool_call_id=ctx.current_tcl,
                path=path, change_type=info["change_type"], patch_sha256_after=sha, additions=info["additions"],
                deletions=info["deletions"], is_test_file=info["is_test_file"], tamper_flags=info["tamper_flags"], created_at=now_iso())
    d.bus.publish(ctx.mission_id, "file.modified", ctx.agent_id, {
        "path": path, "change_type": info["change_type"], "tool_call_id": ctx.current_tcl, "patch_sha256": sha,
        "additions": info["additions"], "deletions": info["deletions"], "is_test_file": info["is_test_file"],
        "tamper_flags": info["tamper_flags"]}, task_id=ctx.task_id)
    weak = {"SKIP_ADDED", "ASSERT_REMOVED", "DELETED"} & set(info["tamper_flags"])
    if weak:
        from ..common.scanners import fingerprint
        from ..state.enums import Severity

        fp = fingerprint("test_tamper", path, ",".join(sorted(info["tamper_flags"])))
        if not any(f["fingerprint"] == fp and f["status"] == "OPEN" for f in d.state.findings(ctx.mission_id)):
            d.state.add_finding(ctx.mission_id, "system", Severity.HIGH, "TEST_TAMPERING", path, None, None,
                                f"existing test file weakened: {', '.join(info['tamper_flags'])}",
                                "Restore the original tests and fix the implementation instead.", 0.9, fp, sha,
                                {"kind": "tool_call", "id": ctx.current_tcl}, "scanner:changed", cwe=None, task_id=ctx.task_id)
    return {"patch_sha256": sha, **{k: info[k] for k in ("additions", "deletions", "is_test_file", "tamper_flags")}}


async def exists_at_base(ctx: ToolContext, path: str) -> bool:
    try:
        await git(ctx.workspace, "cat-file", "-e", f"{ctx.base_commit}:{path}")
        return True
    except Exception:  # noqa: BLE001
        return False
