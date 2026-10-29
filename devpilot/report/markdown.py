"""Render a ``MissionReport`` as ``REPORT.md`` following docs/06 section 7.

Every factual row cites evidence ids. Model claims live in their own section and are never mixed with
verified outcomes.
"""

from __future__ import annotations

from datetime import datetime

from devpilot.report.model import ACRow, EvidenceRef, MissionReport

NONE = "_None._"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _refs(refs: list[EvidenceRef]) -> str:
    if not refs:
        return "_no evidence_"
    return ", ".join(f"{r.id} ({_cell(r.summary)})" if r.summary else r.id for r in refs)


def fmt_duration(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60}m{s % 60:02d}s"


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S UTC")


def _short(sha: str | None) -> str:
    return sha[:7] if sha else "none"


def _ac_table(rows: list[ACRow], *, with_conf: bool) -> list[str]:
    head = (
        "| AC | Criterion | Confidence | Evidence |" if with_conf else "| AC | Criterion | Why | Evidence |"
    )
    out = [head, "|----|-----------|------------|----------|"]
    for r in rows:
        if with_conf:
            third = f"{r.confidence:.2f}" if r.confidence is not None else "-"
        else:
            why = r.reason or ""
            if r.counterexample:
                why += f" Counterexample: {r.counterexample}"
            third = f"**{r.status}** {_cell(why)}".strip()
        out.append(f"| {r.ac_id} | {_cell(r.text)} | {third} | {_refs(r.evidence)} |")
    return out


def render_markdown(report: MissionReport) -> str:
    r = report
    L: list[str] = []
    if r.consistency_errors:
        L.append(
            "> 🚨 **CONSISTENCY CHECK FAILED - this report was force-written. Do not trust its VERIFIED rows.**"
        )
        L += [f"> - {e}" for e in r.consistency_errors]
        L.append("")
    L.append(f"# DevPilot Mission Report - {r.mission_id}")
    outcome = r.outcome + (
        "" if r.outcome_final else " (projected: the report is written before the final state)"
    )
    if r.applied:
        who = r.applied_by or "unknown"
        applied = f"yes (approved by {who}, applied at {fmt_time(r.applied_at)})"
    else:
        applied = "no"
    L.append(f"**Outcome:** {outcome} · **Applied:** {applied}")
    if r.outcome_reason:
        L.append(f"**Reason:** {_cell(r.outcome_reason)}")
    L.append(f'**Request:** "{_cell(r.request)}"')
    L.append("")

    L.append(
        f"## ✅ Verified (backed by passing test runs on the final tree, workspace_sha {_short(r.final_tree_sha)})"
    )
    L += _ac_table(r.verified, with_conf=True) if r.verified else [NONE]
    L.append("")

    L.append("## ❌ Failed")
    L += _ac_table(r.failed, with_conf=False) if r.failed else [NONE]
    L.append("")
    L.append("## ⚠️ Unverified")
    L += _ac_table(r.unverified, with_conf=False) if r.unverified else [NONE]
    L.append("")

    L.append("## 🗣️ Model claims (NOT verified)")
    if r.claims:
        for c in r.claims:
            task = f" [{c.task_key}]" if c.task_key else ""
            L.append(f'- {c.source_agent}{task}: "{_cell(c.text)}" - no evidence ({c.source})')
    else:
        L.append(NONE)
    L.append("")

    L.append("## 🔁 Feedback loops")
    if r.feedback_loops:
        for lp in r.feedback_loops:
            L.append(f"{lp.index}. {lp.narrative}")
            extra: list[str] = []
            if lp.cited_evidence:
                extra.append(f"decision cited {', '.join(lp.cited_evidence)}")
            for tn in lp.triage:
                extra.append(
                    f"triage {tn.fingerprint}: {tn.error_type} in {tn.nodeid}; fix direction: {_cell(tn.fix_direction)}"
                )
            if lp.fix_summary:
                extra.append(f"fix applied: {_cell(lp.fix_summary)}")
            L += [f"   - {x}" for x in extra]
    else:
        L.append(NONE)
    if r.strategy_changes:
        L.append("")
        L.append("**Strategy changes**")
        L += [
            f"- {s.task_key or '-'}: {s.from_action or '-'} → {s.to_action} ({_cell(s.reason)})"
            for s in r.strategy_changes
        ]
    L.append("")
    L.append("**Guard overrides**")
    if r.guard_overrides:
        L += [
            f"- {g.task_key or '-'}: {g.proposed} → {g.final} by guard `{g.guard}` ({_cell(g.reason)})"
            for g in r.guard_overrides
        ]
    else:
        L.append("_None - no guard overrode a decision._")
    L.append("")

    L.append("## 🔍 Review & Security")
    rs = r.review_security
    if rs.review_decisions:
        L.append("Reviewer: " + ", ".join(f"{k} {v}" for k, v in rs.review_decisions.items()) + ".")
    else:
        L.append("Reviewer: no review ran.")
    if rs.security_decision:
        run = ", ".join(rs.scanners_run) or "none"
        un = ", ".join(rs.scanners_unavailable) or "none"
        L.append(f"Security: {rs.security_decision} (scanners run: {run}; unavailable: {un}).")
    else:
        L.append("Security: no inspection ran.")
    if rs.counts_by_severity:
        L.append(
            "Findings by severity: " + ", ".join(f"{k} {v}" for k, v in rs.counts_by_severity.items()) + "."
        )
        for fr in rs.findings:
            if fr.proven:
                proof = f"proven ({', '.join(fr.evidence_ids)})" if fr.evidence_ids else "proven"
            else:
                proof = "unproven claim"
            L.append(
                f"- [{fr.severity}] {fr.source}/{fr.lens_or_scanner} {fr.location}: {_cell(fr.description)} - {proof}"
            )
    else:
        L.append("Findings: none.")
    L.append("")

    L.append("## 📋 Plan history")
    for p in r.plan_history:
        rev = (
            f"revised because: {_cell(p.revised_because)}"
            if p.revised_because
            else "no revision reason (initial plan)"
        )
        L.append(
            f"- v{p.version} ({p.n_tasks} task{'s' if p.n_tasks != 1 else ''}: {', '.join(p.task_keys)}) - {rev}"
        )
    if not r.plan_history:
        L.append(NONE)
    L.append("")

    L.append("## 🧾 Changed files")
    if r.changed_files:
        parts = []
        for cf in r.changed_files:
            if cf.added is None:
                note = " (agent-reported, not diff-validated)" if cf.source == "agent-reported" else ""
                parts.append(cf.path + note)
            else:
                parts.append(f"{cf.path} (+{cf.added} -{cf.removed})")
        L.append(", ".join(parts))
    else:
        L.append(NONE)
    L.append("")

    t = r.tests
    L.append("## 🧪 Tests")
    base = f"{t.baseline_totals} ({t.baseline_evidence})" if t.baseline_totals is not None else "not run"
    fin = (
        f"{t.final_totals} ({t.final_evidence}, scope {t.final_scope})"
        if t.final_totals is not None
        else "not run"
    )
    L.append(f"Baseline: {base} · Final: {fin}")
    L.append("Regressions: " + (", ".join(t.regressions) if t.regressions else "none"))
    L.append("")

    b = r.budget
    L.append("## ⏱️ Budget usage")
    L.append(
        f"fix_cycles {b.fix_cycles}/{b.max_fix_cycles} · tokens {b.tokens_total:,}/{b.max_tokens:,} · "
        f"cost ${b.cost_usd:.4f}/${b.max_cost_usd:.2f} · wall clock {fmt_duration(b.wall_clock_s)} · "
        f"tool calls {b.tool_calls}"
    )
    L.append("")

    if r.human_decisions:
        L.append("## 🙋 Human decisions")
        for h in r.human_decisions:
            ans = h.choice or _cell(h.free_text or "")
            L.append(f"- {h.gate} gate: {ans} (by {h.actor} via {h.source} at {fmt_time(h.at)})")
        L.append("")

    L.append("## Pre-existing issues (not addressed)")
    if t.pre_existing:
        L += [f"- {p.nodeid} {p.note} ({p.evidence_id}) - out of scope." for p in t.pre_existing]
    else:
        L.append(NONE)
    L.append("")

    L.append("## Evidence appendix")
    L.append("| Id | Kind | Command | Exit | Workspace sha | Log |")
    L.append("|----|------|---------|------|---------------|-----|")
    for e in r.evidence_appendix:
        if not e.known:
            L.append(f"| {e.id} | **unknown** | cited but not in the ledger | - | - | - |")
            continue
        argv = _cell(" ".join(e.argv)) if e.argv else _cell(e.tool or "")
        L.append(
            f"| {e.id} | {e.kind} | `{argv}` | {e.exit_code if e.exit_code is not None else '-'} | "
            f"{_short(e.workspace_sha)} | {e.log_path} |"
        )
    L.append("")
    return "\n".join(L)
