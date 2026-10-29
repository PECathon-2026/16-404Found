"""Security agent: deterministic scanners (evidence tier 3) + optional LLM review (confidence-tagged)."""
from __future__ import annotations

from typing import Any

from ..common.scanners import fingerprint
from ..common.tamper import analyze_patch
from ..state.enums import FindingStatus, MessageType, Severity
from ..tools.ws import compute_patch
from .context import make_ctx
from .prompts import SECURITY
from .runtime import AgentRuntime
from .schemas import SecurityReview

OPEN = {"OPEN", "DISPUTED", "FIX_PROPOSED"}
LLM_TOOLS = ["fs.read", "fs.search", "fs.list", "git.diff", "mission.record_finding"]


class SecurityAgent:
    def __init__(self, rt: AgentRuntime):
        self.rt, self.deps = rt, rt.deps

    async def run(self, mission_id: str, task_id: str | None, attempt: int = 1) -> dict[str, Any]:
        s = self.deps.state
        mission = s.mission(mission_id)
        task = s.task(task_id) if task_id else None
        async with self.rt.execution(mission_id, "security", task_id, attempt) as exe:
            ctx = make_ctx(self.deps, mission, "security", task, exe.id)
            reg = self.rt.registry
            patch, sha = await compute_patch(ctx)
            sec = await reg.call(ctx, "sec.scan_secrets", {})
            pat = await reg.call(ctx, "sec.scan_patterns", {})
            dep = await reg.call(ctx, "sec.audit_deps", {})
            qual = await reg.call(ctx, "sec.review_quality", {})
            gaps = []
            scanners = [{"tool": "sec.scan_secrets", "ok": sec.ok, "tcl": sec.tool_call_id}, {"tool": "sec.scan_patterns", "ok": pat.ok, "tcl": pat.tool_call_id},
                        {"tool": "sec.audit_deps", "ok": dep.ok, "tcl": dep.tool_call_id}, {"tool": "sec.review_quality", "ok": qual.ok, "tcl": qual.tool_call_id}]
            for sc, r in ((("sec.scan_secrets"), sec), ("sec.scan_patterns", pat), ("sec.audit_deps", dep)):
                if not r.ok:
                    gaps.append(f"{sc} did not run: {(r.error or {}).get('message')}")
            found: list[tuple[dict[str, Any], str]] = []
            for r in (sec, pat, qual):
                for it in (r.data or {}).get("findings", []):
                    found.append((it, r.tool_call_id))
            existing = [f for f in s.findings(mission_id) if f["raised_by"] == "security" and f["source"].startswith("scanner")]
            seen_fps = {f["fingerprint"] for f in existing}
            current_fps = set()
            new_findings = []
            for it, tcl in found:
                current_fps.add(it["fingerprint"])
                if it["fingerprint"] in seen_fps:
                    continue
                f = s.add_finding(
                    mission_id, "security", Severity(it["severity"]), it["category"], it["file"], it["line"], it["line"], it["evidence"],
                    it["recommendation"], it["confidence"], it["fingerprint"], sha, {"kind": "tool_call", "id": tcl, "locator": f"{it['rule']}@{it['file']}:{it['line']}"},
                    f"scanner:{it.get('scope', 'changed')}", cwe=it.get("cwe"), task_id=task_id)
                new_findings.append(f)
            resolved = []
            for f in existing:
                if f["status"] in OPEN and f["fingerprint"] not in current_fps:
                    s.set_finding_status(f["id"], FindingStatus.RESOLVED, patch_sha=sha, actor="security")
                    resolved.append(f["id"])
            # test-tampering findings raised by the system resolve when the weakening is gone from the patch
            weak_now = {w["path"] for w in analyze_patch(patch)["weakened_assertions"]}
            for f in s.findings(mission_id):
                if f["category"] == "TEST_TAMPERING" and f["status"] in OPEN and f["file"] not in weak_now:
                    s.set_finding_status(f["id"], FindingStatus.RESOLVED, patch_sha=sha, actor="security")
                    resolved.append(f["id"])
            llm_notes: list[str] = []
            if self.rt.router.enabled_for(mission, "security") and sha:
                out = await self.rt.loop(ctx, role="security", system=SECURITY, tool_names=LLM_TOOLS,
                                         user=f"Review this patch (sha {sha[:12]}):\n{patch[:12000]}\nScanner findings already recorded: {len(found)}. "
                                              "Add only issues the scanners missed.",
                                         result_name="submit_review", result_desc="Finish the review.", result_model=SecurityReview, max_tool_calls=12)
                if out.ok:
                    llm_notes = out.result.quality_notes
                else:
                    gaps.append(f"LLM review did not complete: {out.error}")
            all_f = s.findings(mission_id)
            open_f = [f for f in all_f if f["status"] in OPEN]
            blocking = [f for f in open_f if Severity(f["severity"]).rank >= Severity.HIGH.rank]
            verdict = "BLOCKING" if blocking else ("NON_BLOCKING_ISSUES" if open_f or gaps else "CLEAR")
            report = {"verdict": verdict, "patch_sha256": sha, "new_findings": [f["id"] for f in new_findings], "resolved": resolved,
                      "open": [f["id"] for f in open_f], "gaps": gaps, "scanners": scanners, "quality_notes": llm_notes}
            exe.result = report
            ev = [{"kind": "tool_call", "id": sec.tool_call_id}, {"kind": "tool_call", "id": pat.tool_call_id}]
            s.post_message(mission_id, "security", "master", MessageType.TASK_RESULT,
                           {"summary": f"{verdict}: {len(new_findings)} new, {len(resolved)} resolved, {len(open_f)} open"
                                       + (f"; gaps: {'; '.join(gaps)}" if gaps else ""), "verdict": verdict}, ev, task_id=task_id,
                           severity=Severity.HIGH if blocking else Severity.INFO)
            for f in new_findings:
                if Severity(f["severity"]).rank >= Severity.MEDIUM.rank:
                    s.post_message(mission_id, "security", "developer", MessageType.CRITIQUE,
                                   {"summary": f"{f['severity']} {f['category']} at {f['file']}:{f['line_start']}: {f['recommendation']}",
                                    "finding_id": f["id"], "blocking": Severity(f["severity"]).rank >= Severity.HIGH.rank,
                                    "location": {"file": f["file"], "line_start": f["line_start"]}},
                                   [f["evidence_ref"]] if f["evidence_ref"] else ev, task_id=task_id, severity=Severity(f["severity"]))
                    self.deps.bus.publish(mission_id, "critique.raised", "security", {"from": "security", "to": "developer", "finding_id": f["id"],
                                                                                   "summary": f"{f['category']} at {f['file']}:{f['line_start']}"}, task_id=task_id)
            for fid in resolved:
                self.deps.bus.publish(mission_id, "critique.resolved", "security", {"finding_id": fid, "resolution": "rescan-clean"}, task_id=task_id)
            _ = fingerprint
            return report
