"""Testing agent (QA): deterministic, tool-driven. Real runs, baseline comparison, classification, critiques.

Design note: the tester does not use an LLM. Its value is trustworthy evidence, and a model adds failure modes
(summarising away output) without adding capability. It still communicates through typed messages."""
from __future__ import annotations

from typing import Any

from ..common.parsers import fingerprint
from ..db import test_runs
from ..state.enums import MessageType, Severity
from .context import make_ctx
from .runtime import AgentRuntime


class TesterAgent:
    def __init__(self, rt: AgentRuntime):
        self.rt, self.deps = rt, rt.deps

    async def baseline(self, mission_id: str) -> dict[str, Any]:
        mission = self.deps.state.mission(mission_id)
        async with self.rt.execution(mission_id, "tester") as exe:
            ctx = make_ctx(self.deps, mission, "tester", exe_id=exe.id)
            r = await self.rt.registry.call(ctx, "check.test", {"kind": "BASELINE"})
            data = r.data or {"outcome": (r.error or {}).get("outcome", "UNAVAILABLE"), **(r.error or {})}
            exe.result = {"outcome": data.get("outcome"), "summary": data.get("summary"), "baseline": True}
            if data.get("test_run_id"):
                self.deps.state.update_mission(mission_id, baseline_run_id=data["test_run_id"])
            self.deps.state.post_message(mission_id, "tester", "master", MessageType.TASK_RESULT,
                                         {"summary": f"baseline: {data.get('outcome')} {data.get('summary') or ''}"},
                                         [{"kind": "tool_call", "id": r.tool_call_id}])
            return data

    def _baseline_failures(self, mission_id: str) -> set[str]:
        runs = [r for r in self.deps.state.test_runs(mission_id) if r["kind"] == "BASELINE"]
        return {f["test_id"] for f in (runs[-1]["failures"] or [])} if runs else set()

    async def run(self, mission_id: str, task_id: str | None, attempt: int = 1) -> dict[str, Any]:
        s = self.deps.state
        mission = s.mission(mission_id)
        task = s.task(task_id) if task_id else None
        async with self.rt.execution(mission_id, "tester", task_id, attempt) as exe:
            ctx = make_ctx(self.deps, mission, "tester", task, exe.id)
            reg = self.rt.registry
            t = await reg.call(ctx, "check.test", {"kind": "TEST"})
            lint = await reg.call(ctx, "check.lint", {})
            build = await reg.call(ctx, "check.build", {})
            data: dict[str, Any] = t.data or {"outcome": (t.error or {}).get("outcome", "UNAVAILABLE"), "failures": [], "tried": (t.error or {}).get("tried", [])}
            base_fail = self._baseline_failures(mission_id)
            failures = []
            for f in data.get("failures", []):
                failures.append({**f, "caused_by_patch": f["test_id"] not in base_fail})
            regressions = [f["test_id"] for f in failures if f["caused_by_patch"] and data.get("outcome") == "RED"]
            only_preexisting = data.get("outcome") == "RED" and failures and not regressions
            lint_red = bool(lint.data and lint.data.get("outcome") == "RED")
            build_red = bool(build.data and build.data.get("outcome") == "RED")
            outcome = data.get("outcome")
            if outcome in ("GREEN", "NO_TESTS") and not lint_red and not build_red:
                rec = "PASS"
            elif outcome == "UNAVAILABLE":
                rec = "BLOCKED"
            else:
                rec = "REPAIR"
            sm = data.get("summary") or {}
            human = (f"{sm.get('passed', 0)}/{sm.get('total', 0)} passed" + (f", {sm.get('failed')} failed" if sm.get("failed") else "")
                     + (f", {sm.get('errored')} errors" if sm.get("errored") else "")) if sm else "no tests executed"
            report = {
                "recommendation": rec, "outcome": outcome, "summary": data.get("summary"), "failures": failures, "regressions": regressions,
                "only_preexisting_failures": bool(only_preexisting), "fingerprint": data.get("fingerprint"), "degraded": bool(data.get("degraded")),
                "tried": data.get("tried", []), "lint": (lint.data or {}).get("outcome", "UNAVAILABLE" if lint.error else None),
                "build": (build.data or {}).get("outcome", "UNAVAILABLE" if build.error else None),
                "patch_sha256": data.get("patch_sha256") or mission["current_patch_sha256"], "test_run_id": data.get("test_run_id"),
            }
            exe.result = report
            ev = [{"kind": "tool_call", "id": t.tool_call_id}] + ([{"kind": "test_run", "id": data["test_run_id"]}] if data.get("test_run_id") else [])
            sev = Severity.HIGH if regressions else (Severity.MEDIUM if rec != "PASS" else Severity.INFO)
            s.post_message(mission_id, "tester", "master", MessageType.TASK_RESULT,
                           {"summary": f"{rec}: {outcome}, {human}", "recommendation": rec, "failures": len(failures)},
                           ev, task_id=task_id, severity=sev)
            # direct critique to the developer, one per root-cause cluster (first suspected file)
            clusters: dict[str, list[dict[str, Any]]] = {}
            for f in failures:
                clusters.setdefault((f.get("suspected_files") or ["unknown"])[0], []).append(f)
            for file, fs in clusters.items():
                s.post_message(mission_id, "tester", "developer", MessageType.CRITIQUE,
                               {"summary": f"{len(fs)} failing test(s) point at {file}: {fs[0]['message'][:120]}", "blocking": True,
                                "tests": [f["test_id"] for f in fs], "failure_class": fs[0]["class"], "suspected_file": file},
                               ev, task_id=task_id, severity=sev)
                self.deps.bus.publish(mission_id, "critique.raised", "tester", {"from": "tester", "to": "developer", "summary": f"{file}: {fs[0]['message'][:100]}",
                                                                             "finding_id": None}, task_id=task_id)
            _ = test_runs, fingerprint
            return report
