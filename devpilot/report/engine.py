"""Deterministic report engine: ``build_report`` turns an event log + ``Mission`` into a ``MissionReport``.

No LLM decides what is verified. AC status comes from ``ac_rules.ac_status`` evaluated against the final
tree; model claims are collected separately and can never appear under Verified.
``consistency_check`` is a defence-in-depth assertion over the finished report.
"""

from __future__ import annotations

import json
import re
from typing import Any

from devpilot.core.events import Event, EventType
from devpilot.core.models import (
    ACStatus,
    ACVerdict,
    Evidence,
    Mission,
    MissionSpec,
    MissionStatus,
    RepoBrief,
    ScoredVerdict,
    TestCaseResult,
    TestClass,
    TestOutcome,
    TestRun,
    VerificationMethod,
)
from devpilot.orchestrator import ac_rules
from devpilot.report.model import (
    ACRow,
    BudgetSummary,
    ChangedFile,
    Claim,
    EvidenceAppendixRow,
    EvidenceRef,
    FeedbackLoop,
    FindingRow,
    GuardOverride,
    HumanDecisionRow,
    MissionReport,
    PlanVersion,
    PreExisting,
    ReviewSecurity,
    StrategyChange,
    TestSummary,
    TriageNote,
)

_EVIDENCE_ID = re.compile(r"E-\d{4,}")
_NO_TREE = "<no-final-tree>"
_RETRYING = {
    "RETRY_SAME_AGENT",
    "REASSIGN",
    "ESCALATE_MODEL",
    "TOURNAMENT",
    "ROLLBACK",
    "REPLAN",
    "INVESTIGATE",
}


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------


def derive_final_tree_sha(mission: Mission, events: list[Event]) -> str | None:
    """Best event-log answer to "which tree is final": the applied tree, else the last verified diff."""
    for e in reversed(events):
        if e.type == EventType.APPLIED and e.payload.get("tree_sha"):
            return str(e.payload["tree_sha"])
    if mission.verdicts:
        return mission.verdicts[-1].diff_sha
    return None


def parse_diff(diff_text: str) -> list[ChangedFile]:
    """Per-file +/- line counts from a unified diff."""
    files: dict[str, list[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            current = m.group(2) if m else line.split()[-1]
            files.setdefault(current, [0, 0])
        elif current is not None:
            if line.startswith("+") and not line.startswith("+++"):
                files[current][0] += 1
            elif line.startswith("-") and not line.startswith("---"):
                files[current][1] += 1
    return [ChangedFile(path=p, added=a, removed=r) for p, (a, r) in files.items()]


def _one_line(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _ref(mission: Mission, eid: str) -> EvidenceRef:
    ev = mission.evidence.get(eid)
    if ev is None:
        return EvidenceRef(id=eid, summary="not in the evidence ledger", known=False)
    return EvidenceRef(id=eid, summary=_one_line(ev.summary))


def _cited(av: ACVerdict | None) -> list[str]:
    return list(dict.fromkeys(eid for c in (av.checks if av else []) for eid in c.evidence_ids))


def _av(sv: ScoredVerdict | None, ac_id: str) -> ACVerdict | None:
    if sv is None:
        return None
    return next((v for v in sv.verdict.per_ac if v.ac_id == ac_id), None)


def _related_evidence(mission: Mission, ac_id: str, sha: str, cited: list[str]) -> list[str]:
    ids = set(cited)
    for ev in mission.evidence.values():
        if ev.workspace_sha == sha and ev.kind in ac_rules.EXECUTION_KINDS and ac_id in ev.ac_ids:
            ids.add(ev.id)
    return sorted(ids)


# --------------------------------------------------------------------------------------
# acceptance criteria
# --------------------------------------------------------------------------------------


def _ac_rows(mission: Mission, sha: str) -> list[ACRow]:
    sv = ac_rules.latest_verdict_for(mission, sha)
    rows: list[ACRow] = []
    for state in mission.acs:
        ac = state.ac
        status = ac_rules.ac_status(ac, mission, sha)
        av = _av(sv, ac.id)
        conf: float | None = None
        if av is not None:
            conf = sv.confidence_by_ac.get(ac.id) if sv is not None else None
            if conf is None:
                conf = ac_rules.confidence(av)
        cited = _cited(av)
        if status == ACStatus.VERIFIED:
            ev_ids = ac_rules.supporting_evidence_ids(mission, ac.id, sha)
        else:
            ev_ids = _related_evidence(mission, ac.id, sha, cited)
        reason: str | None = None
        cx: str | None = None
        if status == ACStatus.FAILED:
            reason = av.reasoning if av else "failed"
            cx = av.counterexample if av else None
        elif status != ACStatus.VERIFIED:
            reason = _unverified_reason(status, av, ac.verification_methods, sv is not None)
            cx = av.counterexample if av else None
        rows.append(
            ACRow(
                ac_id=ac.id,
                text=ac.text,
                status=status.value,
                priority=ac.priority,
                confidence=conf,
                evidence=[_ref(mission, e) for e in ev_ids],
                reason=reason,
                counterexample=cx,
            )
        )
    return rows


def _unverified_reason(
    status: ACStatus, av: ACVerdict | None, methods: list[VerificationMethod], has_verdict: bool
) -> str:
    if methods == [VerificationMethod.MANUAL]:
        return "manual-only criterion: a human must confirm it"
    if status == ACStatus.CLAIMED:
        return "only an agent's report supports it; no passing execution evidence on the final tree"
    if av is None:
        return (
            "the verifier gave no verdict for this criterion on the final tree"
            if has_verdict
            else "no verifier verdict is bound to the final tree"
        )
    if av.verdict == "INCONCLUSIVE":
        return f"verifier was inconclusive: {_one_line(av.reasoning)}"
    return "verifier passed it, but no passing execution evidence is bound to the final tree"


# --------------------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------------------


def _latest_by(mission: Mission, output_type: str, key: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sub in mission.submissions.values():
        if sub.output_type == output_type:
            out[key(sub)] = sub
    return out


def _claims(mission: Mission) -> list[Claim]:
    claims: list[Claim] = []
    seen: set[tuple[str, str]] = set()

    def add(text: str, agent: str, source: str, task: str | None = None) -> None:
        k = (agent, text.strip())
        if text.strip() and k not in seen:
            seen.add(k)
            claims.append(Claim(text=text.strip(), source_agent=agent, source=source, task_key=task))

    for sub in _latest_by(mission, "ChangeReport", lambda s: s.task_key or "").values():
        for c in sub.payload.get("claims", []):
            add(str(c), sub.agent_id, "ChangeReport.claims", sub.task_key)
    spec = mission.spec
    if isinstance(spec, MissionSpec):
        for a in spec.assumptions:
            add(a, "shogun", "MissionSpec.assumptions")
    brief = mission.brief
    if isinstance(brief, RepoBrief):
        for q in brief.open_questions:
            add(q, "scout", "RepoBrief.open_questions")
    for sub in _latest_by(mission, "ReviewReport", lambda s: str(s.payload.get("lens"))).values():
        for f in sub.payload.get("findings", []):
            if not f.get("proven"):
                add(
                    f"[{f.get('severity')}] {f.get('location')}: {f.get('description')}",
                    sub.agent_id,
                    "ReviewFinding(proven=false)",
                )
    for sub in _latest_by(mission, "SecurityReport", lambda s: "security").values():
        for f in sub.payload.get("findings", []):
            if f.get("source") == "llm" and not f.get("evidence_ids") and not f.get("exploit_probe_evidence"):
                add(
                    f"[{f.get('severity')}] {f.get('location')}: {f.get('description')}",
                    sub.agent_id,
                    "SecurityFinding(unproven, source=llm)",
                )
    return claims


# --------------------------------------------------------------------------------------
# review & security
# --------------------------------------------------------------------------------------


def _review_security(mission: Mission) -> ReviewSecurity:
    out = ReviewSecurity()
    counts: dict[str, int] = {}
    for lens, sub in sorted(
        _latest_by(mission, "ReviewReport", lambda s: str(s.payload.get("lens"))).items()
    ):
        out.review_decisions[lens] = str(sub.payload.get("decision"))
        for f in sub.payload.get("findings", []):
            sev = str(f.get("severity"))
            counts[sev] = counts.get(sev, 0) + 1
            out.findings.append(
                FindingRow(
                    source="review",
                    lens_or_scanner=lens,
                    severity=sev,
                    location=str(f.get("location")),
                    description=str(f.get("description")),
                    proven=bool(f.get("proven")),
                    evidence_ids=list(f.get("evidence_ids", [])),
                )
            )
    sec = _latest_by(mission, "SecurityReport", lambda s: "security").get("security")
    if sec is not None:
        out.security_decision = str(sec.payload.get("decision"))
        out.scanners_run = list(sec.payload.get("scanners_run", []))
        out.scanners_unavailable = list(sec.payload.get("scanners_unavailable", []))
        for f in sec.payload.get("findings", []):
            sev = str(f.get("severity"))
            counts[sev] = counts.get(sev, 0) + 1
            ev = list(f.get("evidence_ids", []))
            if f.get("exploit_probe_evidence"):
                ev.append(f["exploit_probe_evidence"])
            out.findings.append(
                FindingRow(
                    source="security",
                    lens_or_scanner=str(f.get("source")),
                    severity=sev,
                    location=str(f.get("location")),
                    description=str(f.get("description")),
                    proven=bool(ev) or f.get("source") != "llm",
                    evidence_ids=ev,
                )
            )
    out.counts_by_severity = dict(sorted(counts.items()))
    return out


# --------------------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------------------


def _tests(mission: Mission) -> TestSummary:
    runs = mission.test_runs
    baseline = next((r for r in runs if r.scope == "baseline"), None)
    candidates = [r for r in runs if r.scope == "full"] or [
        r for r in runs if r.scope not in ("baseline", "probe")
    ]
    final = candidates[-1] if candidates else None
    out = TestSummary(
        baseline_totals=dict(baseline.totals) if baseline else None,
        baseline_evidence=baseline.evidence_id if baseline else None,
        final_totals=dict(final.totals) if final else None,
        final_evidence=final.evidence_id if final else None,
        final_scope=final.scope if final else None,
        regressions=list(final.regressions) if final else [],
    )
    seen: set[str] = set()

    def add(case: TestCaseResult, run: TestRun, note: str) -> None:
        if case.nodeid not in seen:
            seen.add(case.nodeid)
            out.pre_existing.append(PreExisting(nodeid=case.nodeid, evidence_id=run.evidence_id, note=note))

    if baseline is not None:
        for c in baseline.cases:
            if c.outcome in (TestOutcome.FAILED, TestOutcome.ERROR):
                add(c, baseline, "failing at baseline")
    if final is not None:
        for c in final.cases:
            if c.classification == TestClass.STILL_FAILING:
                add(c, final, "failing before and after the change")
    return out


# --------------------------------------------------------------------------------------
# feedback loops
# --------------------------------------------------------------------------------------


def _verdict_trigger(mission: Mission, trig: Event, kinds: set[str]) -> tuple[str, str, list[str]]:
    scored = ScoredVerdict.model_validate(trig.payload["verdict"])
    fails = [a for a in scored.verdict.per_ac if a.verdict == "FAIL"]
    if "verifier" in kinds or fails:
        kind = "verifier_reject"
    elif "review" in kinds:
        kind = "review_reject"
    elif "security" in kinds:
        kind = "security_block"
    else:
        kind = "verifier_reject" if scored.verdict.overall == "REJECT" else "other"
    ev = list(dict.fromkeys(e for a in fails for c in a.checks for e in c.evidence_ids))
    if not ev:  # fall back to the execution evidence on the rejected tree
        ev = sorted(
            e.id
            for e in mission.evidence.values()
            if e.workspace_sha == scored.diff_sha and e.kind in ac_rules.EXECUTION_KINDS
        )
    if fails:
        text = "Verifier " + ", ".join(f"{a.ac_id} FAIL" for a in fails)
        cx = next((a.counterexample for a in fails if a.counterexample), None)
        if cx:
            text += f" (counterexample {_one_line(cx, 100)})"
    else:
        text = f"Verifier {scored.verdict.overall}"
    return kind, text, ev


def _build_loops(mission: Mission, events: list[Event]) -> list[FeedbackLoop]:
    by_seq = {e.seq: e for e in events}
    decisions = [e for e in events if e.type == EventType.DECISION]
    loops: list[FeedbackLoop] = []
    for i, d in enumerate(decisions):
        prev_seq = decisions[i - 1].seq if i else 0
        next_seq = decisions[i + 1].seq if i + 1 < len(decisions) else 10**12
        task = d.payload.get("task_key") or d.task_key
        action = str(d.payload.get("final_action"))
        proposed = d.payload.get("proposed_action")
        guard = d.payload.get("overridden_by_guard")
        dec_id = f"D-{i + 1:04d}"
        sub = mission.submissions.get(str(d.payload.get("submission_id")))
        cited = [str(c) for c in (sub.payload.get("cited_evidence", []) if sub else [])]

        # findings routed to this decision's task since the previous decision
        findings = [
            e.payload["finding"]
            for e in events
            if e.type == EventType.FINDING
            and prev_seq < e.seq < d.seq
            and e.payload["finding"].get("status") == "open"
            and e.payload["finding"].get("routed_to") in (task, None)
        ]
        fkinds = {str(f["kind"]) for f in findings}
        trig_seq = d.payload.get("trigger_event_seq")
        trig = by_seq.get(int(trig_seq)) if trig_seq is not None else None
        if trig is not None and trig.seq >= d.seq:
            trig = None

        kind: str = "other"
        text = ""
        trig_ev: list[str] = []
        if trig is not None and trig.type == EventType.TEST_RUN:
            tr = trig.payload["test_run"]
            kind = "tests_red"
            trig_ev = [str(tr["evidence_id"])]
            text = f"{tr['evidence_id']} {'red' if tr['verdict'] != 'green' else 'green'}"
        elif trig is not None and trig.type == EventType.VERDICT:
            kind, text, trig_ev = _verdict_trigger(mission, trig, fkinds)
        else:
            text = _one_line(trig.summary if trig else str(d.summary), 100)
            if "triage" in fkinds:
                kind = "tests_red"
            elif "verifier" in fkinds:
                kind = "verifier_reject"
            elif "review" in fkinds:
                kind = "review_reject"
            elif "security" in fkinds:
                kind = "security_block"
        if (
            kind in ("review_reject", "security_block")
            and trig is not None
            and trig.type == EventType.VERDICT
        ):
            text = "Review requested changes" if kind == "review_reject" else "Security blocked"

        triage: list[TriageNote] = []
        for f in findings:
            p = f.get("payload", {})
            if f["kind"] == "triage" and p.get("fingerprint"):
                triage.append(
                    TriageNote(
                        nodeid=str(p.get("nodeid", "")),
                        fingerprint=str(p["fingerprint"]),
                        error_type=str(p.get("error_type", "")),
                        fix_direction=str(p.get("fix_direction", "")),
                    )
                )
        fids = list(dict.fromkeys(str(f["id"]) for f in findings))
        fkind = sorted(fkinds)[0] if fkinds else None

        # next attempt and its outcome
        after = [e for e in events if d.seq < e.seq < next_seq]
        start = next(
            (
                e
                for e in after
                if e.type == EventType.TASK_STATE_CHANGED
                and e.payload.get("to") == "IN_PROGRESS"
                and e.payload.get("attempt")
                and (task is None or e.payload.get("task_key") == task)
            ),
            None,
        ) or next(
            (
                e
                for e in after
                if e.type == EventType.TASK_STATE_CHANGED
                and e.payload.get("to") == "IN_PROGRESS"
                and e.payload.get("attempt")
            ),
            None,
        )
        attempt_n: int | None = None
        fix_summary: str | None = None
        outcome = "none"
        out_ev: list[str] = []
        if start is not None:
            attempt_n = int(start.payload["attempt"]["n"])
            outcome = "unknown"
            submitted = next(
                (
                    e
                    for e in after
                    if e.type == EventType.TASK_STATE_CHANGED
                    and e.payload.get("task_key") == start.payload.get("task_key")
                    and e.payload.get("to") == "SUBMITTED"
                    and (e.payload.get("attempt") or {}).get("n") == attempt_n
                ),
                None,
            )
            if submitted is not None:
                csub = mission.submissions.get(str(submitted.payload["attempt"].get("submission_id")))
                if csub is not None and csub.output_type == "ChangeReport":
                    fix_summary = _one_line(
                        str(csub.payload.get("approach") or csub.payload.get("hypothesis") or ""), 240
                    )
            run_ev = next((e for e in after if e.type == EventType.TEST_RUN and e.seq > start.seq), None)
            if run_ev is not None:
                tr = run_ev.payload["test_run"]
                outcome = "green" if tr["verdict"] == "green" else "red"
                out_ev = [str(tr["evidence_id"])]
                if kind != "tests_red":
                    vd = next((e for e in after if e.type == EventType.VERDICT and e.seq > run_ev.seq), None)
                    if vd is not None and outcome == "green":
                        outcome = (
                            "accepted"
                            if vd.payload["verdict"]["verdict"]["overall"] == "ACCEPT"
                            else "rejected"
                        )

        loop = FeedbackLoop(
            index=len(loops) + 1,
            task_key=task,
            trigger_kind=kind,
            trigger_text=text,
            trigger_evidence=trig_ev,
            finding_ids=fids,
            finding_kind=fkind,
            decision_id=dec_id,
            action=action,
            proposed_action=str(proposed) if proposed else None,
            cited_evidence=cited,
            guard_override=str(guard) if guard else None,
            next_attempt=attempt_n,
            outcome=outcome,
            outcome_evidence=out_ev,
            triage=triage,
            fix_summary=fix_summary,
        )
        loop.narrative = _narrative(loop)
        loops.append(loop)
    return loops


def _narrative(lp: FeedbackLoop) -> str:
    parts: list[str] = []
    if lp.trigger_kind == "tests_red":
        parts.append(lp.trigger_text)
    else:
        ev = ", ".join([*lp.trigger_evidence, *lp.finding_ids])
        head = lp.trigger_text
        parts.append(f"{head} [{ev}]" if ev else head)
    if lp.finding_ids and lp.trigger_kind == "tests_red":
        parts.append(f"{lp.finding_kind or 'finding'} {', '.join(lp.finding_ids)}")
    dec = f"{lp.decision_id} {lp.action}"
    if lp.guard_override:
        dec += f" [guard override of {lp.proposed_action}: {lp.guard_override}]"
    parts.append(dec)
    if lp.next_attempt is not None:
        tail = (
            f"attempt {lp.next_attempt} {lp.outcome}"
            if lp.outcome != "unknown"
            else f"attempt {lp.next_attempt}"
        )
        if lp.outcome_evidence:
            tail += f" ({', '.join(lp.outcome_evidence)})"
        parts.append(tail)
    else:
        parts.append("no further attempt")
    return " → ".join(parts)


# --------------------------------------------------------------------------------------
# remaining sections
# --------------------------------------------------------------------------------------


def _plan_history(mission: Mission) -> list[PlanVersion]:
    return [
        PlanVersion(
            version=p.version,
            n_tasks=len(p.plan.tasks),
            rationale=_one_line(p.plan.rationale, 240),
            revised_because=p.plan.revised_because,
            task_keys=[t.key for t in p.plan.tasks],
        )
        for p in mission.plans
    ]


def _budget(mission: Mission, events: list[Event]) -> BudgetSummary:
    b = mission.budget
    fix = max(
        [b.fix_cycles]
        + [
            int(e.payload.get("fix_cycles", 0))
            for e in events
            if e.type in (EventType.BUDGET_WARNING, EventType.MISSION_FINISHED)
        ]
    )
    span = (events[-1].ts - events[0].ts).total_seconds() if len(events) > 1 else 0.0
    return BudgetSummary(
        tokens_in=b.tokens_in,
        tokens_out=b.tokens_out,
        tokens_total=b.tokens_in + b.tokens_out,
        max_tokens=b.limits.max_tokens_mission,
        cost_usd=round(b.cost_usd, 6),
        max_cost_usd=b.limits.max_cost_usd,
        fix_cycles=fix,
        max_fix_cycles=b.limits.max_fix_cycles,
        wall_clock_s=round(max(b.wall_clock_s, span), 3),
        tool_calls=b.tool_calls,
    )


def _changed_files(
    mission: Mission, diff_names: list[str] | None, diff_text: str | None
) -> list[ChangedFile]:
    if diff_text:
        return parse_diff(diff_text)
    if diff_names is not None:
        return [ChangedFile(path=n) for n in diff_names]
    names: list[str] = []
    for sub in _latest_by(mission, "ChangeReport", lambda s: s.task_key or "").values():
        if sub.payload.get("status") == "done":
            names += [str(n) for n in sub.payload.get("files_changed", [])]
    return [ChangedFile(path=n, source="agent-reported") for n in dict.fromkeys(names)]


def _human_decisions(mission: Mission) -> list[HumanDecisionRow]:
    rows: list[HumanDecisionRow] = []
    for hd in mission.human_decisions:
        prompt = mission.prompts.get(hd.prompt_id)
        rows.append(
            HumanDecisionRow(
                gate=prompt.gate if prompt else "?",
                title=prompt.title if prompt else "",
                choice=hd.choice,
                free_text=hd.free_text,
                actor=hd.actor,
                source=hd.source,
                at=hd.created_at.isoformat(),
            )
        )
    return rows


def _outcome(
    mission: Mission, events: list[Event], rows: list[ACRow], applied: bool
) -> tuple[str, bool, str | None]:
    reason = next(
        (str(e.payload.get("reason")) for e in reversed(events) if e.type == EventType.STATE_CHANGED), None
    )
    if mission.status.terminal:
        return mission.status.value, True, mission.outcome_reason or reason
    must = [r for r in rows if r.priority == "must"]
    ok = applied and bool(must) and all(r.status == "VERIFIED" for r in must)
    projected = MissionStatus.COMPLETED_VERIFIED if ok else MissionStatus.COMPLETED_PARTIAL
    return projected.value, False, reason


def _strategy_and_guards(events: list[Event]) -> tuple[list[StrategyChange], list[GuardOverride]]:
    sc: list[StrategyChange] = []
    go: list[GuardOverride] = []
    for e in events:
        p = e.payload
        if e.type == EventType.STRATEGY_CHANGED:
            sc.append(
                StrategyChange(
                    seq=e.seq,
                    task_key=p.get("task") or e.task_key,
                    from_action=str(p["from"]) if p.get("from") else None,
                    to_action=str(p.get("to")),
                    reason=str(p.get("reason", "")),
                )
            )
        elif e.type == EventType.GUARD_OVERRIDE:
            go.append(
                GuardOverride(
                    seq=e.seq,
                    task_key=p.get("task") or e.task_key,
                    proposed=str(p.get("proposed")),
                    final=str(p.get("final")),
                    guard=str(p.get("guard", "")),
                    reason=str(p.get("reason", "")),
                )
            )
    return sc, go


def _appendix(mission: Mission, report: MissionReport) -> list[EvidenceAppendixRow]:
    body = report.model_dump_json(exclude={"evidence_appendix", "consistency_errors"})
    ids = sorted(set(_EVIDENCE_ID.findall(body)))
    rows: list[EvidenceAppendixRow] = []
    for eid in ids:
        ev: Evidence | None = mission.evidence.get(eid)
        if ev is None:
            rows.append(
                EvidenceAppendixRow(id=eid, known=False, summary="cited but not in the evidence ledger")
            )
        else:
            rows.append(
                EvidenceAppendixRow(
                    id=eid,
                    kind=ev.kind.value,
                    tool=ev.tool,
                    argv=ev.argv,
                    exit_code=ev.exit_code,
                    workspace_sha=ev.workspace_sha,
                    log_path=ev.log_path,
                    summary=_one_line(ev.summary),
                )
            )
    return rows


# --------------------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------------------


def build_report(
    mission: Mission,
    events: list[Event],
    *,
    final_tree_sha: str | None,
    diff_names: list[str] | None = None,
    diff_text: str | None = None,
) -> MissionReport:
    """Pure, deterministic. AC status is ``ac_rules.ac_status`` on ``final_tree_sha``; nothing else decides."""
    sha = final_tree_sha or _NO_TREE
    rows = _ac_rows(mission, sha)
    applied_ev = next((e for e in reversed(events) if e.type == EventType.APPLIED), None)
    applied = applied_ev is not None
    applied_by: str | None = None
    if applied:
        for hd in reversed(mission.human_decisions):
            prompt = mission.prompts.get(hd.prompt_id)
            if prompt is not None and prompt.gate == "apply":
                applied_by = hd.actor
                break
    outcome, final, reason = _outcome(mission, events, rows, applied)
    strategy, guards = _strategy_and_guards(events)
    report = MissionReport(
        mission_id=mission.id,
        request=mission.request,
        outcome=outcome,
        outcome_final=final,
        outcome_reason=reason,
        applied=applied,
        applied_by=applied_by,
        applied_at=applied_ev.ts.isoformat() if applied_ev else None,
        final_tree_sha=final_tree_sha,
        verified=[r for r in rows if r.status == "VERIFIED"],
        failed=[r for r in rows if r.status == "FAILED"],
        unverified=[r for r in rows if r.status not in ("VERIFIED", "FAILED")],
        claims=_claims(mission),
        feedback_loops=_build_loops(mission, events),
        strategy_changes=strategy,
        guard_overrides=guards,
        plan_history=_plan_history(mission),
        review_security=_review_security(mission),
        tests=_tests(mission),
        changed_files=_changed_files(mission, diff_names, diff_text),
        budget=_budget(mission, events),
        human_decisions=_human_decisions(mission),
    )
    report.evidence_appendix = _appendix(mission, report)
    return report


def consistency_check(report: MissionReport, mission: Mission) -> list[str]:
    """Defence in depth: every VERIFIED claim needs passing execution evidence on the final tree.

    Also flags an AC that the projected mission state calls VERIFIED while the report (recomputed from
    the evidence ledger) does not. Returns human-readable problems; empty means consistent.
    """
    errors: list[str] = []
    sha = report.final_tree_sha
    for row in report.verified:
        good = [
            ref.id
            for ref in row.evidence
            if (ev := mission.evidence.get(ref.id)) is not None
            and sha is not None
            and ev.workspace_sha == sha
            and ev.kind in ac_rules.EXECUTION_KINDS
            and ev.exit_code == 0
        ]
        if not good:
            errors.append(
                f"{row.ac_id} is VERIFIED without passing execution evidence bound to final tree {sha or '(none)'}"
            )
    verified_ids = {r.ac_id for r in report.verified}
    for state in mission.acs:
        if state.status == ACStatus.VERIFIED and state.ac.id not in verified_ids:
            errors.append(
                f"{state.ac.id} is projected VERIFIED (AC_STATUS_CHANGED) but has no passing execution "
                f"evidence bound to final tree {sha or '(none)'}"
            )
    if report.outcome == MissionStatus.COMPLETED_VERIFIED.value:
        bad = [r.ac_id for r in (*report.failed, *report.unverified) if r.priority == "must"]
        if bad or not report.verified:
            errors.append(f"outcome is COMPLETED_VERIFIED but must-have ACs are not verified: {bad}")
        if not report.applied:
            errors.append("outcome is COMPLETED_VERIFIED but the change was not applied")
    return errors


def report_json(report: MissionReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=False)
