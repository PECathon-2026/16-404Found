"""Planning agent (Architect): reconnaissance + PlanResult. Cannot write files (permission matrix)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..common.detect import detect
from ..state.enums import MessageType
from .context import make_ctx
from .plan_validator import validate_plan
from .prompts import PLANNER
from .runtime import AgentRuntime
from .schemas import PlanResult

TOOLS = ["fs.list", "fs.read", "fs.search", "git.status", "shell.run"]


@dataclass
class PlanOutcome:
    plan: PlanResult | None
    error: str | None = None
    evidence: list[dict[str, Any]] | None = None


class PlannerAgent:
    def __init__(self, rt: AgentRuntime):
        self.rt, self.deps = rt, rt.deps

    def _recon_digest(self, mission: dict[str, Any]) -> str:
        from pathlib import Path

        ws = Path(mission["workspace_path"])
        info = detect(ws)
        top = sorted(p.name + ("/" if p.is_dir() else "") for p in ws.iterdir() if p.name != ".git")[:60]
        return json.dumps({"top_level": top, **{k: info[k] for k in ("languages", "frameworks", "detected_commands", "conventions", "entry_points")}}, indent=1)

    async def plan(self, mission_id: str, notes: list[str], replan: dict[str, Any] | None = None) -> PlanOutcome:
        mission = self.deps.state.mission(mission_id)
        async with self.rt.execution(mission_id, "planner") as exe:
            ctx = make_ctx(self.deps, mission, "planner", exe_id=exe.id)
            parts = [f"REQUEST:\n{mission['request']}", f"REPOSITORY DIGEST (deterministic recon, verify with tools):\n{self._recon_digest(mission)}"]
            from ..services.memory import recall

            mem = recall(self.deps, mission["repository_id"])
            if mem:
                parts.append("NOTES FROM EARLIER MISSIONS ON THIS REPOSITORY (hints, not verified facts):\n" + "\n".join(f"- {m}" for m in mem))
            if notes:
                parts.append("HUMAN CLARIFICATIONS / NOTES:\n" + "\n".join(f"- {n}" for n in notes))
            if replan:
                parts.append("REPLAN REQUIRED. Completed work is kept; plan only the remaining work and fix the cause.\n" + json.dumps(replan, indent=1)[:4000])
            user = "\n\n".join(parts)
            kw = dict(role="planner", system=PLANNER, tool_names=TOOLS, result_name="submit_plan",
                      result_desc="Submit the plan: objectives, acceptance criteria with verification methods, tasks, risks, ambiguities.",
                      result_model=PlanResult, max_tool_calls=20)
            out = await self.rt.loop(ctx, user=user, **kw)  # type: ignore[arg-type]
            for _ in range(2):
                if not out.ok:
                    exe.result, exe.status, exe.error = {"error": out.error}, "ERROR", out.error
                    return PlanOutcome(None, out.error)
                errs = validate_plan(out.result)
                if out.tool_calls_made < 1:
                    errs.append("you must inspect the repository with tools before planning")
                if not errs:
                    break
                out = await self.rt.loop(ctx, user="The plan was rejected:\n- " + "\n- ".join(errs) + "\nFix it and call submit_plan again.",
                                         messages=out.messages, **kw)  # type: ignore[arg-type]
            else:
                errs = validate_plan(out.result) if out.ok else [out.error or "planning failed"]
                if errs:
                    exe.status, exe.error = "ERROR", "; ".join(errs)[:300]
                    return PlanOutcome(None, "plan failed validation: " + "; ".join(errs))
            plan: PlanResult = out.result
            evidence = [{"kind": "tool_call", "id": t} for t in out.tool_call_ids[:6]] or [{"kind": "decision", "id": "none"}]
            exe.result = {"criteria": len(plan.acceptance_criteria), "tasks": len(plan.tasks), "ambiguities": len(plan.ambiguities)}
            self.deps.state.post_message(mission_id, "planner", "master", MessageType.TASK_RESULT,
                                         {"summary": f"plan: {len(plan.tasks)} tasks, {len(plan.acceptance_criteria)} criteria, "
                                                     f"{sum(a.blocking for a in plan.ambiguities)} blocking ambiguities"}, evidence)
            return PlanOutcome(plan, None, evidence)
