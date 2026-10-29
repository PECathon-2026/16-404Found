"""Final report (T6.05): partitions VERIFIED outcomes from UNRESOLVED items, agent claims and model claims."""
from __future__ import annotations

from typing import Any

from ..db import agent_executions
from ..deps import Deps

OPEN = {"OPEN", "DISPUTED", "FIX_PROPOSED"}


def build_outcome(deps: Deps, mid: str, terminal: str, reason: str | None = None) -> dict[str, Any]:
    s = deps.state
    m = s.mission(mid)
    sha = m["current_patch_sha256"]
    runs, findings, criteria = s.test_runs(mid), s.findings(mid), s.criteria(mid)
    ver = s.latest_verification(mid)
    verified: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    model_claims: list[dict[str, Any]] = []
    ver_ok = ver is not None and ver["patch_sha256"] == sha
    for c in criteria:
        item = {"id": c["ac_key"], "text": c["text"], "method": c["verification"].get("method"), "evidence": c["evidence_refs"]}
        if c["status"] == "PASS" and ver_ok:
            verified.append({**item, "source": "independent verifier", "status": "PASS"})
        else:
            unresolved.append({**item, "status": c["status"], "why": "not PASS in the verifier report for the final patch"})
    final = [r for r in runs if r["kind"] == "TEST" and r["patch_sha256"] == sha]
    base = [r for r in runs if r["kind"] == "BASELINE"]
    if final and final[-1]["outcome"] in ("GREEN", "NO_TESTS"):
        verified.append({"id": "tests", "text": f"test run on final patch: {final[-1]['outcome']} "
                                               f"({final[-1]['passed']}/{final[-1]['total']} passed)", "source": "system-captured run",
                         "evidence": [{"kind": "test_run", "id": final[-1]["id"]}]})
    elif final:
        unresolved.append({"id": "tests", "text": f"latest test run on final patch is {final[-1]['outcome']}", "evidence": [{"kind": "test_run", "id": final[-1]["id"]}]})
    for f in findings:
        row = {"id": f["id"], "text": f"{f['severity']} {f['category']} at {f['file']}:{f['line_start']}", "evidence": [f["evidence_ref"]] if f["evidence_ref"] else []}
        if f["status"] in OPEN:
            unresolved.append({**row, "status": f["status"]})
        elif f["status"] == "RESOLVED":
            verified.append({**row, "source": "re-scan of the final patch found it gone", "status": "RESOLVED"})
        elif f["status"] == "WAIVED_BY_HUMAN":
            unresolved.append({**row, "status": "WAIVED_BY_HUMAN", "why": f["waive_reason"]})
        if f["source"].startswith("agent:") or f["source"] == "llm":
            model_claims.append({**row, "confidence": f["confidence"], "note": "model-suspected, not scanner-confirmed"})
    for e in deps.db.select(agent_executions, order_by="started_at", where_cols={"mission_id": mid, "agent_id": "developer"}):
        if e["status"] == "OK" and e["result"]:
            unverified.append({"id": e["id"], "text": f"developer self-report: {e['result'].get('summary', '')[:200]}",
                               "note": "agent claim; not used as evidence", "confidence": e["result"].get("confidence")})
    notes = []
    if any(r["outcome"] == "NO_TESTS" for r in final):
        notes.append("The repository has no runnable tests; completion rests on verifier criteria only.")
    if any(r["outcome"] == "UNAVAILABLE" for r in runs):
        notes.append("At some point no test runner was available; evidence was degraded for that run.")
    degraded = [e for e in deps.db.select(agent_executions, where_cols={"mission_id": mid, "agent_id": "tester"}) if (e["result"] or {}).get("degraded")]
    if degraded:
        notes.append("A fallback test runner was used because the preferred one was unavailable.")
    return {
        "terminal_status": terminal, "reason": reason, "mode": m["mode"], "patch_sha256": sha,
        "baseline": ({k: base[-1][k] for k in ("id", "outcome", "total", "passed", "failed")} if base else None),
        "final_tests": ({k: final[-1][k] for k in ("id", "outcome", "total", "passed", "failed")} if final else None),
        "verified": verified, "unresolved": unresolved, "unverified_agent_claims": unverified, "model_claims": model_claims, "notes": notes,
        "repair_cycles": m["repair_cycles"], "replans": m["replans"], "steps": m["steps"], "tokens_used": m["tokens_used"],
        "approvals": [{"id": a["id"], "decision": a["decision"], "patch_sha256": a["patch_sha256"], "comment": a["comment"]} for a in s.approvals(mid)],
    }


def to_markdown(title: str, o: dict[str, Any]) -> str:
    def sec(name: str, items: list[dict[str, Any]]) -> str:
        if not items:
            return f"## {name}\n_none_\n"
        return f"## {name}\n" + "\n".join(f"- **{i.get('id')}** {i.get('text')} ({i.get('source') or i.get('status') or i.get('note') or ''})" for i in items) + "\n"

    head = f"# DevPilot report: {title}\n\n- Result: **{o['terminal_status']}**{(' - ' + o['reason']) if o.get('reason') else ''}\n- Mode: {o['mode']}\n- Patch: `{o['patch_sha256']}`\n"
    head += f"- Baseline tests: {o['baseline']}\n- Final tests: {o['final_tests']}\n- Repair cycles: {o['repair_cycles']} · replans: {o['replans']} · steps: {o['steps']} · tokens: {o['tokens_used']}\n\n"
    notes = "## Notes\n" + "\n".join(f"- {n}" for n in o["notes"]) + "\n" if o["notes"] else ""
    return head + sec("Verified (system / verifier evidence)", o["verified"]) + sec("Unresolved", o["unresolved"]) + \
        sec("Unverified agent claims", o["unverified_agent_claims"]) + sec("Model claims", o["model_claims"]) + notes
