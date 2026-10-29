"""Developer agent (Engineer): implements/repairs inside the workspace via tools only."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..state.enums import MessageType, TaskStatus
from .context import make_ctx
from .prompts import DEVELOPER
from .runtime import AgentRuntime
from .schemas import DeveloperResult

TOOLS = ["fs.read", "fs.list", "fs.search", "fs.edit", "fs.create", "fs.delete", "shell.run", "git.status", "git.diff",
         "git.checkpoint", "check.test", "check.lint", "mission.post_message", "mission.get_state"]


@dataclass
class DevOutcome:
    ok: bool
    error: str | None = None
    summary: str = ""
    changed: bool = False


class DeveloperAgent:
    def __init__(self, rt: AgentRuntime):
        self.rt, self.deps = rt, rt.deps

    def _prompt(self, mission: dict[str, Any], task: dict[str, Any]) -> str:
        s = self.deps.state
        crit = {c["ac_key"]: c for c in s.criteria(mission["id"])}
        served = [f"{k}: {crit[k]['text']}" for k in task["criteria_refs"] if k in crit]
        plan = mission.get("plan_summary") or {}
        parts = [f"TASK {task['key']} ({task['kind']}): {task['title']}\n{task['description']}",
                 f"Files you are expected to touch/create: {task['files_hint']}",
                 "Acceptance criteria this task serves:\n" + "\n".join(f"- {c}" for c in served),
                 f"Repository conventions detected: {json.dumps(plan.get('conventions', {}))}"]
        notes = (mission["config"] or {}).get("human_notes") or []
        if notes:
            parts.append("Human guidance:\n" + "\n".join(f"- {n}" for n in notes))
        fc = task.get("failure_context")
        if fc:
            parts.append("THIS IS A REPAIR. Evidence from the previous attempt (real tool output):\n" + json.dumps(fc, indent=1)[:6000])
            if fc.get("strategy_change"):
                parts.append("The same failure occurred again after your last change. Your previous approach is not working: choose a DIFFERENT approach.")
        return "\n\n".join(parts)

    async def work(self, mission_id: str, task_id: str, attempt: int) -> DevOutcome:
        s = self.deps.state
        mission, task = s.mission(mission_id), s.task(task_id)
        async with self.rt.execution(mission_id, "developer", task_id, attempt) as exe:
            ctx = make_ctx(self.deps, mission, "developer", task, exe.id)
            out = await self.rt.loop(ctx, role="developer", system=DEVELOPER, user=self._prompt(mission, task), tool_names=TOOLS,
                                     result_name="submit_result", result_desc="Report what you did, known gaps and assumptions.",
                                     result_model=DeveloperResult, max_tool_calls=30, max_seconds=420)
            if not out.ok:
                exe.status, exe.error = "ERROR", out.error
                s.post_message(mission_id, "developer", "master", MessageType.STATUS, {"summary": f"BLOCKED: {out.error}", "state": "BLOCKED"},
                               task_id=task_id)
                return DevOutcome(False, out.error)
            res: DeveloperResult = out.result
            cp = await self.rt.registry.call(ctx, "git.checkpoint", {"message": f"{task['key']}: {task['title']}"[:100]})
            changes = [c for c in s.code_changes(mission_id) if c["task_id"] == task_id]
            exe.result = {"summary": res.summary, "known_gaps": res.known_gaps, "assumptions": res.assumptions, "confidence": res.confidence,
                          "checkpoint": cp.data, "files_changed": sorted({c["path"] for c in changes}),
                          "self_reported": True}
            evidence = [{"kind": "tool_call", "id": cp.tool_call_id}] + [{"kind": "tool_call", "id": t} for t in out.tool_call_ids[-4:]]
            s.post_message(mission_id, "developer", "master", MessageType.TASK_RESULT,
                           {"summary": res.summary[:300], "files_changed": exe.result["files_changed"], "known_gaps": res.known_gaps,
                            "note": "self-reported; tester and verifier will re-run everything"},
                           evidence, task_id=task_id, in_reply_to=None)
            s.set_task_status(task_id, TaskStatus.IN_REVIEW, actor="developer")
            return DevOutcome(True, None, res.summary, bool(changes))
