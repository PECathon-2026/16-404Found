"""Render ``report.html``: one self-contained file (inline CSS, no external assets).

Same sections as the Markdown report, a collapsible event timeline, and the report JSON embedded in
``<script type="application/json" id="report-data">`` so a later UI (or a test) can read it back.
"""

from __future__ import annotations

import json
from html import escape as esc

from devpilot.core.events import Event
from devpilot.report.markdown import fmt_duration, fmt_time
from devpilot.report.model import ACRow, EvidenceRef, MissionReport

_CSS = """
:root{--bg:#fafaf8;--fg:#1c1c1a;--muted:#6b6b66;--card:#fff;--line:#e2e2dc;--ok:#1a7f4b;--bad:#b3261e;--warn:#9a6700;--accent:#2457c5}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecece8;--muted:#9a9a93;--card:#1f1f1c;--line:#34342f;--ok:#4cc38a;--bad:#ff7b72;--warn:#e3b341;--accent:#79a8ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.meta{color:var(--muted)}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid var(--line);font-size:.8rem;font-weight:600}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);font-size:.9rem}
th,td{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}
code{font:.85em ui-monospace,Menlo,Consolas,monospace}
.banner{background:var(--bad);color:#fff;padding:10px 14px;border-radius:6px;margin-bottom:16px;font-weight:600}
.claims li{color:var(--warn)}
details{margin-top:8px}summary{cursor:pointer;color:var(--accent)}
.timeline td:first-child{color:var(--muted);white-space:nowrap}
@media (max-width:600px){table{display:block;overflow-x:auto}}
"""


def _refs(refs: list[EvidenceRef]) -> str:
    if not refs:
        return "<em>no evidence</em>"
    return ", ".join(
        f'<code title="{esc(r.summary)}">{esc(r.id)}</code>' + ("" if r.known else " (unknown!)")
        for r in refs
    )


def _ac_table(rows: list[ACRow], with_conf: bool) -> str:
    if not rows:
        return "<p><em>None.</em></p>"
    out = [
        "<table><tr><th>AC</th><th>Criterion</th><th>"
        + ("Confidence" if with_conf else "Why")
        + "</th><th>Evidence</th></tr>"
    ]
    for r in rows:
        if with_conf:
            third = f"{r.confidence:.2f}" if r.confidence is not None else "-"
        else:
            why = (r.reason or "") + (f" Counterexample: {r.counterexample}" if r.counterexample else "")
            third = f'<strong class="{"bad" if r.status == "FAILED" else "warn"}">{esc(r.status)}</strong> {esc(why)}'
        out.append(
            f"<tr><td>{esc(r.ac_id)}</td><td>{esc(r.text)}</td><td>{third if not with_conf else esc(third)}</td><td>{_refs(r.evidence)}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else "<p><em>None.</em></p>"


def render_html(report: MissionReport, events: list[Event]) -> str:
    r = report
    body: list[str] = []
    if r.consistency_errors:
        body.append(
            '<div class="banner">CONSISTENCY CHECK FAILED - force-written report. Do not trust VERIFIED rows.<ul>'
            + "".join(f"<li>{esc(e)}</li>" for e in r.consistency_errors)
            + "</ul></div>"
        )
    good = r.outcome == "COMPLETED_VERIFIED"
    applied = (
        f"yes (approved by {esc(r.applied_by or 'unknown')}, applied {esc(fmt_time(r.applied_at))})"
        if r.applied
        else "no"
    )
    body.append(f"<h1>DevPilot Mission Report - {esc(r.mission_id)}</h1>")
    proj = "" if r.outcome_final else " (projected)"
    body.append(
        f'<p><span class="badge {"ok" if good else "warn"}">{esc(r.outcome)}{proj}</span> '
        f'<span class="meta">Applied: {applied}</span></p>'
    )
    body.append(f'<p class="meta">Request: &ldquo;{esc(r.request)}&rdquo;</p>')

    sha = esc(r.final_tree_sha[:7]) if r.final_tree_sha else "none"
    body.append(f'<h2>✅ Verified <span class="meta">(passing runs on final tree {sha})</span></h2>')
    body.append(_ac_table(r.verified, True))
    body.append("<h2>❌ Failed</h2>" + _ac_table(r.failed, False))
    body.append("<h2>⚠️ Unverified</h2>" + _ac_table(r.unverified, False))

    body.append("<h2>🗣️ Model claims (NOT verified)</h2>")
    body.append(
        '<ul class="claims">'
        + "".join(
            f'<li>{esc(c.source_agent)}: &ldquo;{esc(c.text)}&rdquo; - no evidence <span class="meta">({esc(c.source)})</span></li>'
            for c in r.claims
        )
        + "</ul>"
        if r.claims
        else "<p><em>None.</em></p>"
    )

    body.append("<h2>🔁 Feedback loops</h2>")
    body.append(
        "<ol>" + "".join(f"<li>{esc(lp.narrative)}</li>" for lp in r.feedback_loops) + "</ol>"
        if r.feedback_loops
        else "<p><em>None.</em></p>"
    )
    if r.strategy_changes:
        body.append(
            "<h3>Strategy changes</h3>"
            + _ul(
                [
                    esc(f"{s.task_key}: {s.from_action} → {s.to_action} ({s.reason})")
                    for s in r.strategy_changes
                ]
            )
        )
    body.append(
        "<h3>Guard overrides</h3>"
        + _ul(
            [
                esc(f"{g.task_key}: {g.proposed} → {g.final} by {g.guard} ({g.reason})")
                for g in r.guard_overrides
            ]
        )
    )

    rs = r.review_security
    body.append("<h2>🔍 Review &amp; Security</h2>")
    body.append(
        "<p>Reviewer: "
        + esc(", ".join(f"{k} {v}" for k, v in rs.review_decisions.items()) or "none")
        + f". Security: {esc(rs.security_decision or 'none')} (run: {esc(', '.join(rs.scanners_run) or 'none')}; "
        f"unavailable: {esc(', '.join(rs.scanners_unavailable) or 'none')}).</p>"
    )
    body.append(
        _ul(
            [
                esc(
                    f"[{f.severity}] {f.source}/{f.lens_or_scanner} {f.location}: {f.description} - {'proven' if f.proven else 'unproven claim'}"
                )
                for f in rs.findings
            ]
        )
    )

    body.append("<h2>📋 Plan history</h2>")
    body.append(
        _ul(
            [
                esc(
                    f"v{p.version} ({p.n_tasks} tasks) - "
                    + (f"revised because: {p.revised_because}" if p.revised_because else "initial plan")
                )
                for p in r.plan_history
            ]
        )
    )

    body.append("<h2>🧾 Changed files</h2>")
    body.append(
        _ul(
            [
                f"<code>{esc(f.path)}</code>"
                + (f" (+{f.added} -{f.removed})" if f.added is not None else " (agent-reported)")
                for f in r.changed_files
            ]
        )
    )

    t = r.tests
    body.append("<h2>🧪 Tests</h2>")
    body.append(
        f"<p>Baseline: {esc(str(t.baseline_totals))} ({esc(str(t.baseline_evidence))}) · Final: {esc(str(t.final_totals))} "
        f"({esc(str(t.final_evidence))}) · Regressions: {esc(', '.join(t.regressions) or 'none')}</p>"
    )

    b = r.budget
    body.append("<h2>⏱️ Budget usage</h2>")
    body.append(
        f"<p>fix_cycles {b.fix_cycles}/{b.max_fix_cycles} · tokens {b.tokens_total:,}/{b.max_tokens:,} · "
        f"cost ${b.cost_usd:.4f}/${b.max_cost_usd:.2f} · wall clock {esc(fmt_duration(b.wall_clock_s))} · tool calls {b.tool_calls}</p>"
    )
    if r.human_decisions:
        body.append("<h2>🙋 Human decisions</h2>")
        body.append(
            _ul(
                [
                    esc(f"{h.gate}: {h.choice or h.free_text or ''} (by {h.actor} via {h.source})")
                    for h in r.human_decisions
                ]
            )
        )

    body.append("<h2>Pre-existing issues (not addressed)</h2>")
    body.append(_ul([esc(f"{p.nodeid} {p.note} ({p.evidence_id})") for p in t.pre_existing]))

    body.append(
        "<h2>Evidence appendix</h2><table><tr><th>Id</th><th>Kind</th><th>Command</th><th>Exit</th><th>Workspace sha</th><th>Log</th></tr>"
    )
    for e in r.evidence_appendix:
        argv = " ".join(e.argv) if e.argv else (e.tool or "")
        body.append(
            f"<tr><td><code>{esc(e.id)}</code></td><td>{esc(e.kind or 'unknown')}</td><td><code>{esc(argv)}</code></td>"
            f"<td>{esc(str(e.exit_code) if e.exit_code is not None else '-')}</td><td><code>{esc((e.workspace_sha or '-')[:12])}</code></td>"
            f"<td>{esc(e.log_path or '-')}</td></tr>"
        )
    body.append("</table>")

    rows = "".join(
        f"<tr><td>#{e.seq} {esc(e.ts.strftime('%H:%M:%S'))}</td><td>{esc(e.type.value)}</td><td>{esc(e.actor)}</td><td>{esc(e.summary)}</td></tr>"
        for e in events
    )
    body.append(
        f'<details><summary>Event timeline ({len(events)} events)</summary><table class="timeline">'
        f"<tr><th>When</th><th>Type</th><th>Actor</th><th>Summary</th></tr>{rows}</table></details>"
    )

    data = json.dumps(r.model_dump(mode="json"), indent=2).replace("<", "\\u003c")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>DevPilot report {esc(r.mission_id)}</title><style>{_CSS}</style></head><body><main>"
        + "".join(body)
        + f'</main><script type="application/json" id="report-data">{data}</script></body></html>'
    )
