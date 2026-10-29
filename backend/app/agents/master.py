"""Master agent (Shogun): evidence-based decisions. The deterministic policy is the spine (AGENTS.md §B.1.1);
an LLM may choose among *legal candidates* when one is available, but the guard validates every choice."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..db import agent_executions, approvals
from ..deps import Deps
from ..graph import watchdog
from ..llm.base import LLMError, Msg
from ..state.enums import MasterAction as A
from ..state.enums import MessageType, MissionStatus, Severity, TaskKind, TaskStatus
from ..state.gate import completion_gate
from .prompts import MASTER

DEV_KINDS = {TaskKind.IMPLEMENT, TaskKind.WRITE_TESTS, TaskKind.REPAIR}
OPEN = {"OPEN", "DISPUTED", "FIX_PROPOSED"}


@dataclass
class Decision:
    action: A
    rationale: str
    target_task_id: str | None = None
    target_agent: str | None = None
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    forced_by: str = "POLICY"

    def as_dict(self) -> dict[str, Any]:
        return {"action": str(self.action), "rationale": self.rationale, "target_task_id": self.target_task_id,
                "target_agent": self.target_agent, "evidence_refs": self.evidence_refs, "extra": self.extra, "forced_by": self.forced_by}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Decision:
        return Decision(A(d["action"]), d["rationale"], d.get("target_task_id"), d.get("target_agent"), d.get("evidence_refs", []), d.get("extra", {}), d.get("forced_by", "POLICY"))


class DecideArgs(BaseModel):
    action: A
    rationale: str
    evidence_ids: list[str] = []


class MasterAgent:
    def __init__(self, deps: Deps):
        self.deps = deps

    # ------------------------------------------------------------------ view
    def view(self, mid: str) -> dict[str, Any]:
        s = self.deps.state
        m = s.mission(mid)
        tasks = s.tasks(mid)
        sha = m["current_patch_sha256"]
        execs = self.deps.db.select(agent_executions, order_by="started_at", where_cols={"mission_id": mid})

        def done_for(agent: str) -> dict[str, Any] | None:
            for e in reversed(execs):
                if e["agent_id"] == agent and e["status"] == "OK" and (e["result"] or {}).get("patch_sha256") == sha and not (e["result"] or {}).get("baseline"):
                    return e["result"]
            return None

        return {"m": m, "tasks": tasks, "criteria": s.criteria(mid), "findings": s.findings(mid), "runs": s.test_runs(mid),
                "verification": s.latest_verification(mid), "approvals": s.approvals(mid), "sha": sha,
                "tester": done_for("tester"), "security": done_for("security"), "execs": execs,
                "verifications_for_sha": len([v for v in self.deps.db.select(__import__("app.db", fromlist=["verification_reports"]).verification_reports,
                                                                          where_cols={"mission_id": mid}) if v["patch_sha256"] == sha])}

    def blocking_findings(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        cfg = v["m"]["config"] or {}
        out = []
        for f in v["findings"]:
            if f["status"] not in OPEN or Severity(f["severity"]).rank < Severity.MEDIUM.rank:
                continue
            if f["source"] == "scanner:pre_existing" and not cfg.get("block_on_pre_existing"):
                continue
            out.append(f)
        return out

    def gate(self, v: dict[str, Any]):
        cfg = v["m"]["config"] or {}
        return completion_gate(patch_sha256=v["sha"], criteria=v["criteria"],
                               findings=[f for f in v["findings"] if f["source"] != "scanner:pre_existing" or cfg.get("block_on_pre_existing")],
                               verification=v["verification"], test_runs=self._runs_for_gate(v),
                               tamper_waived=bool(cfg.get("_tamper_waived")))

    def _runs_for_gate(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        """Pre-existing failures may be tolerated when the mission opts in (they must be a subset of the baseline failures)."""
        cfg = v["m"]["config"] or {}
        runs = [dict(r) for r in v["runs"]]
        if cfg.get("allow_preexisting_failures"):
            base = [r for r in runs if r["kind"] == "BASELINE"]
            base_fail = {f["test_id"] for f in (base[-1]["failures"] if base else [])}
            for r in runs:
                if r["kind"] == "TEST" and r["outcome"] == "RED" and {f["test_id"] for f in r["failures"]} <= base_fail:
                    r["outcome"] = "GREEN"
        return runs

    # ------------------------------------------------------------------ policy
    def policy(self, v: dict[str, Any]) -> Decision:
        m, tasks = v["m"], v["tasks"]
        wd = watchdog.check(m, v["runs"])
        if wd:
            return Decision(A(wd.force), wd.reason, evidence_refs=wd.evidence, extra={"kind": wd.kind, "escalation_kind": "ESCALATION"}, forced_by="WATCHDOG")
        plan = m.get("plan_summary") or {}
        live = [t for t in tasks if t["status"] != TaskStatus.SUPERSEDED]
        if not v["criteria"] and not live:
            blocking = [a for a in plan.get("ambiguities", []) if a.get("blocking") and not a.get("answered")]
            if blocking:
                a = blocking[0]
                return Decision(A.ESCALATE, f"requirement is ambiguous: {a['question']}",
                                extra={"escalation_kind": "CLARIFICATION", "question": a["question"], "assumed_default": a.get("assumed_default"),
                                       "options": [{"id": "answer", "label": "Answer the question", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]})
            return Decision(A.PLAN, "no plan yet: reconnaissance and planning required")

        dev = [t for t in live if t["kind"] in DEV_KINDS]
        ready = [t for t in dev if t["status"] == TaskStatus.READY]
        if ready:
            t = ready[0]
            return Decision(A.DELEGATE, f"{t['key']} ({t['kind']}) has all dependencies done", t["id"], "developer")
        in_review = [t for t in dev if t["status"] == TaskStatus.IN_REVIEW]
        pending = [t for t in dev if t["status"] in (TaskStatus.PENDING, TaskStatus.BLOCKED)]
        if in_review:
            first = in_review[0]
            if not v["sha"]:
                return self._repair(v, first, {"reason": "the developer finished without changing any file", "kind": "NO_CHANGES"}, "no changes were made")
            if not (v["tester"] and v["security"]):
                chk = next((t for t in live if t["kind"] == TaskKind.RUN_CHECKS and t["status"] in (TaskStatus.PENDING, TaskStatus.READY)), None)
                return Decision(A.DELEGATE, f"patch {v['sha'][:10]} is unchecked: tester and security run on the same immutable patch",
                                chk["id"] if chk else None, "checks", extra={"patch_sha256": v["sha"]})
            return self._evaluate_checks(v, in_review)
        if pending and not ready:
            return Decision(A.ESCALATE, "tasks are waiting on dependencies that can never complete (deadlock)",
                            extra={"escalation_kind": "ESCALATION", "options": [{"id": "hint", "label": "Give guidance", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]})
        # all dev work is DONE
        ver = v["verification"]
        if not v["tester"] or not v["security"]:
            return Decision(A.DELEGATE, "final checks required before verification", None, "checks", extra={"patch_sha256": v["sha"]})
        if ver is None or ver["patch_sha256"] != v["sha"]:
            if v["verifications_for_sha"] >= 2:
                return Decision(A.ESCALATE, "the independent verifier could not complete twice on this patch",
                                extra={"escalation_kind": "ESCALATION", "options": [{"id": "hint", "label": "Give guidance", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]})
            return Decision(A.VERIFY, "all tasks done and checks green: independent verification of the acceptance criteria")
        if ver["overall"] == "FAIL":
            target = (dev[-1] if dev else tasks[-1])
            ctx = self._verification_failure_context(ver)
            return self._repair(v, target, ctx, "independent verification failed", evidence=[{"kind": "verification", "id": ver["id"]}])
        g = self.gate(v)
        appr = [a for a in v["approvals"] if a["patch_sha256"] == v["sha"] and not a["superseded"]]
        last = appr[-1] if appr else None
        if g.clear and last and last["decision"] == "APPROVED":
            if set(g.needs_ack) <= set(last["acknowledged_criteria"] or []):
                return Decision(A.COMPLETE, "human approved this exact patch; the completion gate is clear", evidence_refs=[{"kind": "decision", "id": last["id"]}],
                                extra={"approval_id": last["id"]})
            return Decision(A.ESCALATE, "approval did not acknowledge manually-verified criteria: " + ", ".join(g.needs_ack),
                            extra={"escalation_kind": "ESCALATION", "options": [{"id": "hint", "label": "Re-approve with acknowledgement", "needs_text": False}]})
        if g.clear:
            return Decision(A.REQUEST_APPROVAL, "verifier passed and the completion gate is clear", evidence_refs=[{"kind": "verification", "id": ver["id"]}],
                            extra={"gate": g.as_dict()})
        reasons = "; ".join(g.reasons)
        if any(x.startswith("open ") for x in g.reasons):
            blocking = self.blocking_findings(v) or [f for f in v["findings"] if f["status"] in OPEN]
            return self._repair(v, dev[-1], {"reason": "gate blocked by open findings", "findings": self._finding_ctx(blocking), "kind": "SECURITY"}, reasons)
        if any("tamper" in x for x in g.reasons):
            return Decision(A.ESCALATE, "existing tests were modified: a human must waive or require a revert", evidence_refs=[{"kind": "verification", "id": ver["id"]}],
                            extra={"escalation_kind": "ESCALATION", "options": [{"id": "waive_tamper", "label": "Waive: the test change is legitimate", "needs_text": True},
                                                                              {"id": "hint", "label": "Require revert (guidance)", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]})
        return Decision(A.ESCALATE, f"completion gate blocked: {reasons}", extra={"escalation_kind": "ESCALATION", "options": [{"id": "hint", "label": "Give guidance", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]})

    # ------------------------------------------------------------------ evaluation of checks
    def _evaluate_checks(self, v: dict[str, Any], in_review: list[dict[str, Any]]) -> Decision:
        t = v["tester"]
        first = in_review[0]
        ev = [{"kind": "test_run", "id": t["test_run_id"]}] if t.get("test_run_id") else []
        if t["recommendation"] == "BLOCKED":
            return Decision(A.ESCALATE, "no test runner is available in the sandbox; refusing to claim success without evidence", evidence_refs=ev,
                            extra={"escalation_kind": "ESCALATION", "kind": "ENV_MISSING_TOOL", "tried": t.get("tried"),
                                   "options": [{"id": "hint", "label": "Tell DevPilot how to run the tests", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]})
        gate_runs = self._runs_for_gate(v)
        cur = [r for r in gate_runs if r["kind"] == "TEST" and r["patch_sha256"] == v["sha"]]
        tests_ok = bool(cur) and cur[-1]["outcome"] in ("GREEN", "NO_TESTS") and t["lint"] != "RED" and t["build"] != "RED"
        blocking = self.blocking_findings(v)
        if not tests_ok:
            ctx = {"kind": "TESTS", "failures": t["failures"][:8], "lint": t["lint"], "build": t["build"], "outcome": t["outcome"],
                   "regressions": t["regressions"], "test_run_id": t.get("test_run_id"), "degraded": t["degraded"]}
            if blocking:
                ctx["findings"] = self._finding_ctx(blocking)
            return self._repair(v, first, ctx, f"tests {t['outcome']}: " + (t["failures"][0]["message"][:100] if t["failures"] else "lint/build failed"), evidence=ev)
        if blocking:
            return self._repair(v, first, {"kind": "SECURITY", "findings": self._finding_ctx(blocking), "reason": "open security/quality findings"},
                                f"{len(blocking)} open finding(s) >= MEDIUM: " + blocking[0]["category"],
                                evidence=[f["evidence_ref"] for f in blocking if f["evidence_ref"]][:3])
        confirm = [r for r in v["runs"] if r["kind"] == "CONFIRM" and r["patch_sha256"] == v["sha"]]
        if not confirm:
            return Decision(A.EXECUTE, "tester reports green: the system re-executes the tests itself instead of trusting the report",
                            target_task_id=first["id"], evidence_refs=ev, extra={"command": "check.test", "patch_sha256": v["sha"]})
        c = confirm[-1]
        if c["outcome"] in ("RED", "ERROR", "UNAVAILABLE"):
            ctx = {"kind": "TESTS", "failures": [{k: f.get(k) for k in ("test_id", "class", "message", "suspected_files", "trace_excerpt")} for f in c["failures"][:8]],
                   "outcome": c["outcome"], "test_run_id": c["id"], "conflict": "the tester reported PASS but the system re-run failed; system evidence wins"}
            return self._repair(v, first, ctx, "system re-execution disagrees with the tester (evidence conflict resolved in favour of the system run)",
                                evidence=[{"kind": "test_run", "id": c["id"]}])
        return Decision(A.ESCALATE, "internal inconsistency: checks are green and confirmed but tasks were not accepted",
                        extra={"escalation_kind": "ESCALATION", "options": [{"id": "abort", "label": "Cancel mission"}]})

    def can_accept(self, v: dict[str, Any]) -> list[dict[str, Any]]:
        """In-review dev tasks that may be accepted: tester PASS + security ran + system confirmation green + nothing blocking."""
        in_review = [t for t in v["tasks"] if t["kind"] in DEV_KINDS and t["status"] == TaskStatus.IN_REVIEW]
        t = v["tester"]
        if not (in_review and v["sha"] and t and v["security"] and t["recommendation"] == "PASS" and not self.blocking_findings(v)):
            return []
        confirm = [r for r in v["runs"] if r["kind"] == "CONFIRM" and r["patch_sha256"] == v["sha"]]
        return in_review if confirm and confirm[-1]["outcome"] in ("GREEN", "NO_TESTS") else []

    def _finding_ctx(self, fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"id": f["id"], "severity": f["severity"], "category": f["category"], "file": f["file"], "line": f["line_start"],
                 "evidence": f["evidence"], "recommendation": f["recommendation"]} for f in fs[:8]]

    def _verification_failure_context(self, ver: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "VERIFICATION", "failed_criteria": [{"id": r["ac_id"], "method": r["method"], "evidence": r["evidence"]} for r in ver["results"] if r["status"] == "FAIL"],
                "new_failures": (ver["regression_check"] or {}).get("new_failures", []), "verification_id": ver["id"]}

    def _repair(self, v: dict[str, Any], failing: dict[str, Any], ctx: dict[str, Any], why: str, evidence: list[dict[str, Any]] | None = None) -> Decision:
        fp, n, ids = watchdog.trailing_fingerprint(v["runs"], (v["m"]["config"] or {}).get("_fp_reset_after"))
        ctx = {**ctx, "attempt": v["m"]["repair_cycles"] + 1, "fingerprint": fp, "same_fingerprint_count": n, "strategy_change": n >= 2,
               "previous_patch_sha256": v["sha"]}
        return Decision(A.RETRY, f"repair needed: {why}", failing["id"], "developer", evidence or [], {"repair": ctx}, "POLICY")

    # ------------------------------------------------------------------ decide
    async def decide(self, mid: str, step: int, router: Any) -> Decision:
        v = self.view(mid)
        accept = self.can_accept(v)
        if accept:  # deterministic effect: evidence is complete, mark the work accepted and unlock dependents
            for t in accept:
                self.deps.state.set_task_status(t["id"], TaskStatus.DONE, actor="master")
            for t in v["tasks"]:
                if t["kind"] in (TaskKind.RUN_CHECKS, TaskKind.SECURITY_REVIEW) and t["status"] not in (TaskStatus.DONE, TaskStatus.SUPERSEDED):
                    self.deps.state.set_task_status(t["id"], TaskStatus.DONE, actor="master")
            self.deps.state.promote_ready(mid)
            v = self.view(mid)
        d = self.policy(v)
        if d.forced_by == "POLICY" and router is not None and router.enabled_for(v["m"], "master"):
            d = await self._consult(mid, v, d, router)
        return d

    async def _consult(self, mid: str, v: dict[str, Any], default: Decision, router: Any) -> Decision:
        """The LLM may pick another *legal* action; the guard below keeps it inside the lifecycle rules."""
        legal = {str(default.action): default}
        if v["tasks"] and v["m"]["replans"] < watchdog.limits(v["m"])["max_replans"]:
            legal[str(A.REPLAN)] = Decision(A.REPLAN, "plan assumptions no longer hold", extra={"replan": {"reason": "master chose to replan"}})
        legal[str(A.ESCALATE)] = Decision(A.ESCALATE, "ask the human", extra={"escalation_kind": "ESCALATION", "options": [{"id": "hint", "label": "Give guidance", "needs_text": True}, {"id": "abort", "label": "Cancel mission"}]})
        digest = {"status": v["m"]["status"], "legal_actions": {k: d.rationale for k, d in legal.items()}, "recommended": str(default.action),
                  "criteria": [(c["ac_key"], c["status"]) for c in v["criteria"]], "tasks": [(t["key"], t["kind"], t["status"]) for t in v["tasks"]],
                  "open_findings": len(self.blocking_findings(v)), "repair_cycles": v["m"]["repair_cycles"]}
        try:
            resp = await router.complete(self.deps, v["m"], "master", None, system=MASTER, messages=[Msg("user", json.dumps(digest))],
                                         tools=[{"name": "decide", "description": "Choose the next action.", "input_schema": DecideArgs.model_json_schema()}], max_tokens=600, temperature=0.1)
            call = next((c for c in resp.tool_calls if c.name == "decide"), None)
            choice = DecideArgs.model_validate(call.args) if call else None
        except (LLMError, Exception):  # noqa: BLE001 - fall back to the deterministic policy
            return default
        if choice and str(choice.action) in legal:
            d = legal[str(choice.action)]
            d.rationale = choice.rationale or d.rationale
            d.forced_by = "LLM"
            return d
        return default

    # ------------------------------------------------------------------ effects (state only; no tools)
    def apply(self, mid: str, d: Decision, step: int) -> None:
        s = self.deps.state
        rec = s.record_decision(mid, step, str(d.action), d.rationale, d.forced_by, d.target_task_id, d.target_agent, d.evidence_refs)
        _ = rec
        if d.action == A.RETRY:
            r = d.extra["repair"]
            failing = s.task(d.target_task_id) if d.target_task_id else None
            cyc = s.bump(mid, "repair_cycles")
            if failing:  # the repair task carries the work forward; a failed repair is FAILED, anything else is handed over (DONE)
                s.set_task_status(failing["id"], TaskStatus.FAILED if failing["kind"] == TaskKind.REPAIR else TaskStatus.DONE, actor="master")
            new = s.add_task(mid, TaskKind.REPAIR, f"Repair: {failing['title']}" if failing else "Repair", f"Fix the failing evidence (cycle {cyc}).",
                             files_hint=(failing or {}).get("files_hint", []), criteria_refs=(failing or {}).get("criteria_refs", []),
                             failure_context=r, plan_version=(failing or {}).get("plan_version", 1))
            s.set_task_status(new["id"], TaskStatus.READY, actor="master")
            self.deps.bus.publish(mid, "repair.initiated", "master", {
                "task_id": new["id"], "failure_fingerprint": r.get("fingerprint"), "attempt": cyc, "strategy_change": bool(r.get("strategy_change")),
                "from_test_run_id": r.get("test_run_id"), "kind": r.get("kind")}, task_id=new["id"])
            s.post_message(mid, "master", "developer", MessageType.TASK_ASSIGN, {"summary": f"repair cycle {cyc}: {d.rationale}", "task_id": new["id"]},
                           d.evidence_refs or [{"kind": "decision", "id": rec["id"]}], task_id=new["id"],
                           idempotency_key=f"{mid}:{new['id']}:TASK_ASSIGN:1", ack_required=True)
        elif d.action == A.VERIFY:
            s.set_status(mid, MissionStatus.VERIFYING, d.rationale)
        elif d.action == A.REQUEST_APPROVAL:
            s.set_status(mid, MissionStatus.AWAITING_APPROVAL, d.rationale)
            m = s.mission(mid)
            self.deps.bus.publish(mid, "approval.requested", "master", {"patch_sha256": m["current_patch_sha256"], "gate": d.extra.get("gate")})
        _ = approvals


__all__ = ["MasterAgent", "Decision", "DEV_KINDS", "OPEN"]
