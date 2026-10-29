"""LangGraph orchestration (ARCHITECTURE.md §B): hub-and-spoke. Every worker node returns to `master`,
which is the only router. Human input and approval are real `interrupt()`s checkpointed by the saver."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..agents.context import make_ctx
from ..agents.developer import DeveloperAgent
from ..agents.master import Decision, MasterAgent
from ..agents.planner import PlannerAgent
from ..agents.runtime import AgentRuntime
from ..agents.security import SecurityAgent
from ..agents.tester import TesterAgent
from ..common.detect import detect
from ..common.ids import new_id, now_iso
from ..common.scanners import scan_injection
from ..db import approvals, human_requests
from ..deps import Deps
from ..llm.router import LLMRouter
from ..sandbox.git import GitError
from ..sandbox.workspace import prepare_workspace
from ..services import publish, reports, repos
from ..services.verification import run_verification
from ..state.enums import MasterAction as A
from ..state.enums import MessageType, Severity, TaskKind, TaskStatus
from ..state.enums import MissionStatus as S
from ..tools.base import ToolRegistry
from ..tools.ws import compute_patch


class GState(TypedDict, total=False):
    mission_id: str
    decision: dict[str, Any] | None
    route: str


class Orchestrator:
    def __init__(self, deps: Deps, registry: ToolRegistry, router: LLMRouter, pause_events: dict[str, asyncio.Event]):
        self.deps, self.registry, self.router = deps, registry, router
        self.rt = AgentRuntime(deps, registry, router)
        self.master = MasterAgent(deps)
        self.planner, self.developer = PlannerAgent(self.rt), DeveloperAgent(self.rt)
        self.tester, self.security = TesterAgent(self.rt), SecurityAgent(self.rt)
        self.pause_events = pause_events

    # ------------------------------------------------------------------ graph
    def build(self, checkpointer: Any):
        g = StateGraph(GState)
        for name, fn in [("ingest", self.n_ingest), ("plan", self.n_plan), ("master", self.n_master), ("dev", self.n_dev),
                         ("checks", self.n_checks), ("exec", self.n_exec), ("verify", self.n_verify), ("human_input", self.n_human),
                         ("approval_gate", self.n_approval), ("finalize", self.n_finalize), ("finalize_failed", self.n_fail),
                         ("finalize_rejected", self.n_rejected)]:
            g.add_node(name, fn)
        g.add_edge(START, "ingest")
        g.add_conditional_edges("ingest", lambda s: "master" if s.get("route") != "end" else END, {"master": "master", END: END})
        g.add_edge("plan", "master")
        for w in ("dev", "checks", "exec", "verify", "human_input"):
            g.add_edge(w, "master")
        g.add_conditional_edges("master", lambda s: s["route"], {
            "plan": "plan", "dev": "dev", "checks": "checks", "exec": "exec", "verify": "verify", "human_input": "human_input",
            "approval_gate": "approval_gate", "finalize": "finalize", "finalize_failed": "finalize_failed", "master": "master", "end": END})
        g.add_conditional_edges("approval_gate", lambda s: s["route"], {"master": "master", "finalize_rejected": "finalize_rejected", "end": END})
        for n in ("finalize", "finalize_failed", "finalize_rejected"):
            g.add_edge(n, END)
        return g.compile(checkpointer=checkpointer)

    # ------------------------------------------------------------------ helpers
    def _fail(self, mid: str, reason: str) -> None:
        m = self.deps.state.mission(mid)
        if m["status"] not in ("COMPLETED", "REJECTED", "FAILED", "CANCELLED"):
            try:
                self.deps.state.set_status(mid, S.FAILED, reason)
            except Exception:  # noqa: BLE001
                self.deps.state.update_mission(mid, status=S.FAILED, status_reason=reason)
        self._outcome(mid, "FAILED", reason)
        self.deps.bus.publish(mid, "mission.failed", "system", {"reason": reason})

    def _outcome(self, mid: str, terminal: str, reason: str | None) -> None:
        o = reports.build_outcome(self.deps, mid, terminal, reason)
        self.deps.state.update_mission(mid, outcome=o)
        run_dir = self.deps.settings.runs_dir / mid
        run_dir.mkdir(parents=True, exist_ok=True)
        import json

        (run_dir / "report.json").write_text(json.dumps(o, indent=1, default=str))
        (run_dir / "report.md").write_text(reports.to_markdown(self.deps.state.mission(mid)["title"], o))
        events = self.deps.bus.history(mid)
        (run_dir / "events.jsonl").write_text("\n".join(json.dumps(e, default=str) for e in events))

    async def _wait_if_paused(self, mid: str) -> None:
        ev = self.pause_events.get(mid)
        while self.deps.state.mission(mid)["status"] == S.PAUSED:
            if ev is None:
                return
            await ev.wait()

    # ------------------------------------------------------------------ nodes
    async def n_ingest(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        d, s = self.deps, self.deps.state
        m = s.mission(mid)
        try:
            repo = d.db.get(__import__("app.db", fromlist=["repositories"]).repositories, m["repository_id"])
            if not repo:
                raise ValueError("repository not found")
            warn = await repos.refresh_clone(d, repo)
            if warn:
                d.bus.publish(mid, "message.sent", "system", {"sender": "system", "recipient": "broadcast", "type": "STATUS", "severity": "LOW", "summary": warn,
                                                              "correlation_id": mid, "message_id": new_id("msg")})
            s.set_status(mid, S.PLANNING, "workspace preparation and baseline", actor="system")
            ws = await prepare_workspace(Path(repo["local_path"]), d.settings.workspaces_dir / mid)
            cfg = {**(m["config"] or {}), "_clock_start": time.time(), "_exclusions": ws.exclusions[:50]}
            s.update_mission(mid, workspace_path=str(ws.path), base_commit=ws.base_commit, config=cfg)
            info = detect(ws.path)
            s.update_mission(mid, plan_summary={"conventions": info["conventions"], "frameworks": info["frameworks"], "languages": info["languages"],
                                                "detected_commands": info["detected_commands"], "ambiguities": []})
            # reconnaissance: planted prompt-injection text in repo content is reported, never followed
            for it in scan_injection(ws.path)[:10]:
                s.add_finding(mid, "system", Severity.LOW, "PROMPT_INJECTION", it["file"], it["line"], it["line"], it["evidence"], it["recommendation"],
                              it["confidence"], it["fingerprint"], None, {"kind": "file", "id": it["file"], "locator": f"L{it['line']}"}, "scanner:pre_existing", cwe=it["cwe"])
            await self.tester.baseline(mid)
        except Exception as e:  # noqa: BLE001
            self._fail(mid, f"could not prepare the workspace: {type(e).__name__}: {str(e)[:200]}")
            return {"route": "end"}
        return {"route": "master"}

    async def n_plan(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        s = self.deps.state
        m = s.mission(mid)
        cfg = m["config"] or {}
        replan = (state.get("decision") or {}).get("extra", {}).get("replan")
        out = await self.planner.plan(mid, cfg.get("clarifications", []), replan)
        if out.plan is None:
            self._fail(mid, out.error or "planning failed")
            return {"route": "end"}
        plan = out.plan
        ps = dict(m["plan_summary"] or {})
        blocking = [a for a in plan.ambiguities if a.blocking]
        ps["ambiguities"] = [{"question": a.question, "blocking": a.blocking, "assumed_default": a.assumed_default, "answered": False} for a in plan.ambiguities]
        ps.update({"objectives": plan.objectives, "risks": plan.risks, "repo_notes": plan.repo_notes})
        if blocking:  # nothing is written: master escalates to the human before any edit
            s.update_mission(mid, plan_summary=ps)
            return {"decision": None}
        version = (m["criteria_version"] or 1) + (1 if replan else 0)
        if replan:
            for t in s.tasks(mid):
                if t["status"] not in (TaskStatus.DONE, TaskStatus.SUPERSEDED, TaskStatus.CANCELLED):
                    s.set_task_status(t["id"], TaskStatus.SUPERSEDED, actor="master")
                    self.deps.bus.publish(mid, "task.superseded", "master", {"task_id": t["id"], "key": t["key"]}, task_id=t["id"])
            s.bump(mid, "replans")
        s.set_criteria(mid, [{"id": c.id, "text": c.text, "verification": c.verification.model_dump()} for c in plan.acceptance_criteria], version)
        refs: dict[str, str] = {}
        impl_ids: list[str] = []
        for t in plan.tasks:
            row = s.add_task(mid, t.kind, t.title, t.description, t.files_hint, t.criteria, [refs[r] for r in t.depends_on if r in refs], plan_version=version)
            refs[t.ref] = row["id"]
            impl_ids.append(row["id"])
        s.add_task(mid, TaskKind.RUN_CHECKS, "Run tests, lint and build on the patch", "Tester runs real checks on the immutable patch.", depends_on=impl_ids, plan_version=version)
        s.add_task(mid, TaskKind.SECURITY_REVIEW, "Security and quality review of the patch", "Scanners plus review; findings carry evidence.", depends_on=impl_ids, plan_version=version)
        s.promote_ready(mid)
        s.update_mission(mid, plan_summary=ps)
        if s.mission(mid)["status"] == S.PLANNING:
            s.set_status(mid, S.EXECUTING, "plan validated and accepted")
        elif s.mission(mid)["status"] == S.AWAITING_HUMAN:
            s.set_status(mid, S.EXECUTING, "replanned")
        return {"decision": None}

    async def n_master(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        s = self.deps.state
        await self._wait_if_paused(mid)
        m = s.mission(mid)
        if m["status"] in ("CANCELLED", "FAILED", "COMPLETED", "REJECTED"):
            return {"route": "end"}
        step = s.bump(mid, "steps")
        d = await self.master.decide(mid, step, self.router)
        self.master.apply(mid, d, step)
        route = {A.PLAN: "plan", A.REPLAN: "plan", A.RETRY: "master", A.VERIFY: "verify", A.ESCALATE: "human_input", A.EXECUTE: "exec",
                 A.REQUEST_APPROVAL: "approval_gate", A.COMPLETE: "finalize", A.FAIL: "finalize_failed"}.get(d.action)
        if d.action == A.DELEGATE:
            route = "dev" if d.target_agent == "developer" else "checks"
        if d.action == A.ESCALATE and s.mission(mid)["status"] != S.AWAITING_HUMAN:
            self._open_human_request(mid, d)
        return {"decision": d.as_dict(), "route": route or "master"}

    def _open_human_request(self, mid: str, d: Decision) -> None:
        s = self.deps.state
        ex = d.extra
        kind = ex.get("escalation_kind", "ESCALATION")
        options = ex.get("options") or [{"id": "hint", "label": "Give guidance", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]
        if kind == "ESCALATION" and not any(o["id"] == "continue" for o in options) and ex.get("kind") in ("REPAIR_LIMIT", "BUDGET", "WALL_CLOCK", "REPEATED_FAILURE"):
            options = [{"id": "continue", "label": "Continue with 3 more repair cycles"}] + options
        question = ex.get("question") or d.rationale
        rid = new_id("hrq")
        d_ = {"id": rid, "mission_id": mid, "kind": kind, "question": question, "options": options, "evidence_refs": d.evidence_refs, "status": "OPEN",
              "answer": None, "created_at": now_iso(), "answered_at": None}
        self.deps.db.insert(human_requests, **d_)
        s.set_status(mid, S.AWAITING_HUMAN, d.rationale)
        s.post_message(mid, "master", "human", MessageType.ESCALATION, {"summary": question, "kind": kind, "options": options, "assumed_default": ex.get("assumed_default")},
                       d.evidence_refs or [{"kind": "decision", "id": "n/a"}], severity=Severity.HIGH if kind == "ESCALATION" else Severity.MEDIUM)
        self.deps.bus.publish(mid, "human.input_requested", "master", {"request_id": rid, "kind": kind, "question": question, "options": options,
                                                                      "evidence_refs": d.evidence_refs, "assumed_default": ex.get("assumed_default")})

    async def n_dev(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        s = self.deps.state
        d = Decision.from_dict(state["decision"] or {})
        tid = d.target_task_id
        assert tid
        task = s.task(tid)
        attempt = (task["retries"] or 0) + 1
        s.db.update(__import__("app.db", fromlist=["tasks"]).tasks, tid, retries=attempt, assignee_agent="developer")
        s.set_task_status(tid, TaskStatus.IN_PROGRESS, actor="developer")
        a = s.post_message(mid, "master", "developer", MessageType.TASK_ASSIGN, {"summary": f"{task['key']}: {task['title']}", "kind": task["kind"]},
                           [{"kind": "decision", "id": "latest"}], task_id=tid, idempotency_key=f"{mid}:{tid}:TASK_ASSIGN:{attempt}", attempt=attempt, ack_required=True)
        s.post_message(mid, "developer", "master", MessageType.TASK_ACK, {"summary": f"accepted {task['key']}"}, task_id=tid,
                       correlation_id=a["correlation_id"], in_reply_to=a["id"], idempotency_key=f"{mid}:{tid}:TASK_ACK:{attempt}")
        s.ack(a["id"])
        out = await self.developer.work(mid, tid, attempt)
        if not out.ok:
            s.set_task_status(tid, TaskStatus.FAILED, actor="developer")
            if "budget" in (out.error or ""):
                pass
            # a failed developer run is evidence for the master: it creates a repair or escalates via the watchdog
            m = s.mission(mid)
            if (task["retries"] or 0) >= (task["max_retries"] or 3) or m["repair_cycles"] >= 8:
                self._fail(mid, f"developer could not complete {task['key']}: {out.error}")
                return {"route": "end"}
            s.set_task_status(tid, TaskStatus.IN_REVIEW, actor="master")  # lets the master's policy create a repair from the missing/partial patch
        return {}

    async def n_checks(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        s = self.deps.state
        for t in s.tasks(mid):
            if t["kind"] in (TaskKind.RUN_CHECKS, TaskKind.SECURITY_REVIEW) and t["status"] in (TaskStatus.PENDING, TaskStatus.READY):
                s.set_task_status(t["id"], TaskStatus.IN_PROGRESS, actor="master")
        chk = next((t for t in s.tasks(mid) if t["kind"] == TaskKind.RUN_CHECKS and t["status"] == TaskStatus.IN_PROGRESS), None)
        sec = next((t for t in s.tasks(mid) if t["kind"] == TaskKind.SECURITY_REVIEW and t["status"] == TaskStatus.IN_PROGRESS), None)
        # tester and security run in parallel on the same immutable patch (both are read-only with respect to source)
        await asyncio.gather(self.tester.run(mid, chk["id"] if chk else None), self.security.run(mid, sec["id"] if sec else None))
        return {}

    async def n_exec(self, state: GState) -> dict[str, Any]:
        """EXECUTE: the system re-runs the tests itself (evidence tier 1) to confirm or contradict the tester's report."""
        mid = state["mission_id"]
        m = self.deps.state.mission(mid)
        ctx = make_ctx(self.deps, m, "system")
        await self.registry.call(ctx, "check.test", {"kind": "CONFIRM"})
        return {}

    async def n_verify(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        m = self.deps.state.mission(mid)
        ctx = make_ctx(self.deps, m, "verifier")
        async with self.rt.execution(mid, "verifier") as exe:
            rep = await run_verification(self.deps, ctx)
            exe.result = {"overall": rep["overall"], "patch_sha256": rep["patch_sha256"], "verification_id": rep["id"]}
        if self.deps.state.mission(mid)["status"] == S.VERIFYING:
            self.deps.state.set_status(mid, S.EXECUTING, f"verification {rep['overall']}") if rep["overall"] == "FAIL" or rep.get("error") else None
        return {}

    # ---- human interaction (real interrupts)
    async def n_human(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        req = next((r for r in reversed(self.deps.state.human_requests(mid)) if r["status"] == "OPEN"), None)
        if req is None:
            return {}
        answer = interrupt({"type": "human_input", "request_id": req["id"], "kind": req["kind"], "question": req["question"]})
        self._apply_answer(mid, req, answer)
        return {}

    def _apply_answer(self, mid: str, req: dict[str, Any], answer: dict[str, Any]) -> None:
        s = self.deps.state
        d = self.deps
        opt, text = answer.get("option") or "answer", (answer.get("text") or "").strip()
        d.db.update(human_requests, req["id"], status="ANSWERED", answer=answer, answered_at=now_iso())
        d.bus.publish(mid, "human.input_received", "human", {"request_id": req["id"], "option": opt})
        s.post_message(mid, "human", "master", MessageType.ANSWER, {"summary": text or opt, "option": opt}, idempotency_key=f"{mid}:{req['id']}:ANSWER")
        m = s.mission(mid)
        cfg = dict(m["config"] or {})
        cfg["_clock_start"] = time.time()
        if opt == "abort":
            s.update_mission(mid, config=cfg)
            s.set_status(mid, S.CANCELLED, "aborted by the human", actor="human")
            self._outcome(mid, "CANCELLED", "aborted by the human")
            return
        if req["kind"] == "CLARIFICATION":
            cfg["clarifications"] = [*cfg.get("clarifications", []), f"Q: {req['question']}  A: {text}"]
            ps = dict(m["plan_summary"] or {})
            ps["ambiguities"] = [{**a, "answered": True} for a in ps.get("ambiguities", [])]
            s.update_mission(mid, config=cfg, plan_summary=ps)
            s.set_status(mid, S.PLANNING, "clarification received", actor="human")
            return
        if opt == "continue":
            cfg["_extra_repair_cycles"] = int(cfg.get("_extra_repair_cycles", 0)) + 3
            runs = s.test_runs(mid)
            cfg["_fp_reset_after"] = runs[-1]["id"] if runs else None
            cfg["limits"] = {**(cfg.get("limits") or {}), "max_tokens": int((cfg.get("limits") or {}).get("max_tokens", 400_000)) * 2}
        elif opt.startswith("waive_finding:"):
            fid = opt.split(":", 1)[1]
            s.set_finding_status(fid, "WAIVED_BY_HUMAN", reason=text or "waived by the human after reviewing both sides", actor="human")
        elif opt == "require_fix":
            for f in s.findings(mid):
                if f["status"] == "DISPUTED":
                    s.set_finding_status(f["id"], "OPEN", actor="human")
            cfg["human_notes"] = [*cfg.get("human_notes", []), "the reviewer upheld the finding: fix it, do not dispute it again"]
        elif opt == "waive_tamper":
            cfg["_tamper_waived"] = True
            cfg["human_notes"] = [*cfg.get("human_notes", []), f"tamper waived: {text}"]
        elif opt.startswith("relax:"):
            ac = opt.split(":", 1)[1]
            crit = next((c for c in s.criteria(mid) if c["ac_key"] == ac), None)
            if crit:
                with d.db.engine.begin() as c:
                    from ..db import acceptance_criteria

                    c.execute(acceptance_criteria.update().where(acceptance_criteria.c.id == crit["id"]).values(
                        verification={"method": "manual_review", "rubric": f"relaxed by human: {text or 'accepted as-is'}"}, status="UNVERIFIED"))
        else:  # hint / answer
            cfg["human_notes"] = [*cfg.get("human_notes", []), text]
            runs = s.test_runs(mid)
            cfg["_fp_reset_after"] = runs[-1]["id"] if runs else None
        s.update_mission(mid, config=cfg)
        s.set_status(mid, S.EXECUTING, f"human guidance received ({opt})", actor="human")

    async def n_approval(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        s = self.deps.state
        m = s.mission(mid)
        resp = interrupt({"type": "approval", "patch_sha256": m["current_patch_sha256"]})
        decision = resp.get("decision")
        sha = m["current_patch_sha256"]
        if resp.get("patch_sha256") != sha:  # defence in depth: the API also rejects stale hashes
            return {"route": "master"}
        row = {"id": new_id("apr"), "mission_id": mid, "patch_sha256": sha, "decision": decision, "comment": resp.get("comment"),
               "acknowledged_criteria": resp.get("acknowledged_criteria", []), "publish": resp.get("publish") or {}, "requested_at": now_iso(),
               "decided_at": now_iso(), "superseded": False}
        self.deps.db.insert(approvals, **row)
        self.deps.bus.publish(mid, "approval.resolved", "human", {"decision": decision, "approval_id": row["id"], "patch_sha256": sha})
        if decision == "REJECTED":
            return {"route": "finalize_rejected"}
        if decision == "CHANGES_REQUESTED":
            s.set_status(mid, S.EXECUTING, "changes requested by the human", actor="human")
            cfg = dict(m["config"] or {})
            cfg["human_notes"] = [*cfg.get("human_notes", []), f"reviewer requested changes: {resp.get('comment')}"]
            s.update_mission(mid, config=cfg)
            self.deps.db.update(approvals, row["id"], superseded=True)
            tasks = [t for t in s.tasks(mid) if t["kind"] in (TaskKind.IMPLEMENT, TaskKind.WRITE_TESTS, TaskKind.REPAIR)]
            new = s.add_task(mid, TaskKind.REPAIR, "Address reviewer feedback", resp.get("comment") or "", (tasks[-1]["files_hint"] if tasks else []),
                             (tasks[-1]["criteria_refs"] if tasks else []), failure_context={"kind": "HUMAN_REVIEW", "comment": resp.get("comment"), "attempt": m["repair_cycles"] + 1})
            s.set_task_status(new["id"], TaskStatus.READY, actor="master")
            s.bump(mid, "repair_cycles")
            self.deps.bus.publish(mid, "repair.initiated", "master", {"task_id": new["id"], "failure_fingerprint": None, "attempt": m["repair_cycles"] + 1,
                                                                    "strategy_change": False, "from_test_run_id": None, "kind": "HUMAN_REVIEW"}, task_id=new["id"])
        return {"route": "master"}

    # ---- terminal nodes
    async def n_finalize(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        d, s = self.deps, self.deps.state
        m = s.mission(mid)
        appr = [a for a in s.approvals(mid) if a["decision"] == "APPROVED" and a["patch_sha256"] == m["current_patch_sha256"]]
        pub = (appr[-1]["publish"] if appr else {}) or {}
        ctx = make_ctx(d, m, "system")
        patch, sha = await compute_patch(ctx)
        applied: dict[str, Any] = {}
        try:
            if sha != m["current_patch_sha256"]:
                raise GitError("patch changed after approval; refusing to apply")
            repo = d.db.get(__import__("app.db", fromlist=["repositories"]).repositories, m["repository_id"])
            assert repo
            o = reports.build_outcome(d, mid, "COMPLETED")
            body = f"Automated change by DevPilot.\n\nMission: {m['title']}\nPatch sha256: {sha}\nVerified: " + "; ".join(v["text"] for v in o["verified"][:6])
            if repo["source_type"] == "LOCAL_PATH":
                applied = await publish.apply_to_local(d, mid, Path(repo["local_path"]), patch)
            else:
                applied = await publish.apply_to_clone(d, mid, Path(repo["local_path"]), patch, m["title"], body)
                token = (pub.get("github_token") or d.settings.github_token or None)
                if pub.get("push"):
                    if not token and repo["github_owner"]:
                        applied["push_error"] = "no GitHub token available (set GITHUB_TOKEN or provide one at approval); the branch exists locally"
                    else:
                        applied.update(await publish.push_branch(Path(repo["local_path"]), applied["branch"], token))
                        if pub.get("open_pr") and repo["github_owner"]:
                            applied.update(await publish.open_pull_request(repo["github_owner"], repo["github_name"], token, applied["branch"],
                                                                         applied["base_branch"], m["title"], body))
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            tok = pub.get("github_token") or d.settings.github_token
            if tok:
                msg = msg.replace(tok, "[REDACTED]")
            applied["error"] = msg[:300]
            self._fail(mid, f"approved, but applying the patch failed: {msg[:200]}")
            return {}
        s.set_status(mid, S.COMPLETED, "approved and applied", actor="master")
        from ..services.memory import remember

        remember(d, mid)
        self._outcome(mid, "COMPLETED", None)
        s.update_mission(mid, outcome={**s.mission(mid)["outcome"], "applied": applied})
        d.bus.publish(mid, "mission.completed", "master", {"applied": applied})
        return {}

    async def n_fail(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        d = (state.get("decision") or {})
        self._fail(mid, d.get("rationale") or "mission failed")
        return {}

    async def n_rejected(self, state: GState) -> dict[str, Any]:
        mid = state["mission_id"]
        self.deps.state.set_status(mid, S.REJECTED, "rejected by the human; the source repository was not modified", actor="human")
        self._outcome(mid, "REJECTED", "rejected by the human")
        return {}
