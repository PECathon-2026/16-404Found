"""Deterministic acceptance-criterion rules (docs/06 section 6 and docs/11 section 7). No LLM, no I/O.

``ac_status`` decides what an AC *is*; ``confidence`` scores how strongly the verifier's checks
support it. Neither can be influenced by an agent's prose.
"""

from __future__ import annotations

from collections.abc import Iterable

from devpilot.core.models import (
    AcceptanceCriterion,
    ACStatus,
    ACVerdict,
    CheckResult,
    Evidence,
    EvidenceKind,
    Mission,
    ScoredVerdict,
    VerificationMethod,
)

#: Evidence kinds that count as *execution* evidence for VERIFIED.
EXECUTION_KINDS: frozenset[EvidenceKind] = frozenset(
    {
        EvidenceKind.TEST_RUN,
        EvidenceKind.PROBE_RUN,
        EvidenceKind.PROPERTY_RUN,
        EvidenceKind.DIFFERENTIAL_RUN,
    }
)

#: docs/11 section 7: 0.4 probe + 0.2 property + 0.2 differential + 0.1 mutation + 0.1 coverage.
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "probe": 0.4,
    "property": 0.2,
    "differential": 0.2,
    "mutation": 0.1,
    "coverage": 0.1,
}


def _passing_evidence(mission: Mission, ac_id: str, sha: str, cited: Iterable[str]) -> list[Evidence]:
    """Execution evidence with exit code 0 produced on exactly ``sha`` that bears on ``ac_id``.

    Evidence counts if the ledger tags it with the AC *or* the verifier's verdict cites it for the AC.
    """
    cited_ids = set(cited)
    return [
        ev
        for ev in mission.evidence.values()
        if ev.workspace_sha == sha
        and ev.kind in EXECUTION_KINDS
        and ev.exit_code == 0
        and (ac_id in ev.ac_ids or ev.id in cited_ids)
    ]


def latest_verdict_for(mission: Mission, diff_sha: str) -> ScoredVerdict | None:
    """The most recent ScoredVerdict bound to ``diff_sha`` (verdicts for other diffs are stale)."""
    for sv in reversed(mission.verdicts):
        if sv.diff_sha == diff_sha:
            return sv
    return None


def _ac_verdict(sv: ScoredVerdict | None, ac_id: str) -> ACVerdict | None:
    if sv is None:
        return None
    return next((v for v in sv.verdict.per_ac if v.ac_id == ac_id), None)


def _claimed(mission: Mission, ac_id: str) -> bool:
    """An agent asserted the AC: a Samurai finished (``done``) a task that lists it."""
    for sub in mission.submissions.values():
        if sub.output_type != "ChangeReport" or sub.payload.get("status") != "done":
            continue
        task = mission.tasks.get(sub.task_key or "")
        if task is not None and ac_id in task.acceptance_refs:
            return True
    return False


def _cited(av: ACVerdict | None) -> list[str]:
    return [eid for c in (av.checks if av else []) for eid in c.evidence_ids]


def ac_status(ac: AcceptanceCriterion, mission: Mission, final_tree_sha: str) -> ACStatus:
    """Status of one AC against the final tree (docs/06 section 6).

    * VERIFIED needs passing execution evidence on ``final_tree_sha`` AND the latest verdict bound to that
      same diff saying PASS for this AC.
    * FAILED if that latest verdict says FAIL.
    * MANUAL-only ACs stay UNVERIFIED (a human must confirm).
    * CLAIMED when only an agent's report supports it.
    * Otherwise UNVERIFIED.

    ``ac`` may also be an ``ACState`` (its ``.ac`` is used).
    """
    crit: AcceptanceCriterion = getattr(ac, "ac", ac)
    av = _ac_verdict(latest_verdict_for(mission, final_tree_sha), crit.id)
    passing = _passing_evidence(mission, crit.id, final_tree_sha, _cited(av))
    if passing and av is not None and av.verdict == "PASS":
        return ACStatus.VERIFIED
    if av is not None and av.verdict == "FAIL":
        return ACStatus.FAILED
    if crit.verification_methods == [VerificationMethod.MANUAL]:
        return ACStatus.UNVERIFIED
    if _claimed(mission, crit.id) and not passing:
        return ACStatus.CLAIMED
    return ACStatus.UNVERIFIED


def supporting_evidence_ids(mission: Mission, ac_id: str, final_tree_sha: str) -> list[str]:
    """Evidence ids (sorted) that back ``ac_id`` on ``final_tree_sha``; used for AC_STATUS_CHANGED."""
    av = _ac_verdict(latest_verdict_for(mission, final_tree_sha), ac_id)
    return sorted(ev.id for ev in _passing_evidence(mission, ac_id, final_tree_sha, _cited(av)))


def _score(checks: list[CheckResult]) -> float:
    """Mean per-check score: the metric (clamped to 0..1) if given, else 1.0 / 0.0 for passed / failed."""
    vals = [
        (min(1.0, max(0.0, c.metric)) if c.metric is not None else (1.0 if c.passed else 0.0)) for c in checks
    ]
    return sum(vals) / len(vals)


def confidence_components(verdict: ACVerdict) -> dict[str, float]:
    """Component scores that are *present* in the verdict's checks (absent components are omitted).

    * probe: PROBE checks (falling back to ACCEPTANCE_TEST / EXISTING_TEST checks when no probe exists,
      so an AC proven by executed tests alone is not scored zero);
    * property, differential: checks of that method;
    * mutation / coverage: checks whose ``detail`` mentions "mutation" / "coverage" (their ``metric``
      carries the kill rate / coverage ratio).
    """
    checks = verdict.checks
    groups: dict[str, list[CheckResult]] = {
        "probe": [c for c in checks if c.method == VerificationMethod.PROBE],
        "property": [c for c in checks if c.method == VerificationMethod.PROPERTY],
        "differential": [c for c in checks if c.method == VerificationMethod.DIFFERENTIAL],
    }
    if not groups["probe"]:
        groups["probe"] = [
            c
            for c in checks
            if c.method in (VerificationMethod.ACCEPTANCE_TEST, VerificationMethod.EXISTING_TEST)
        ]
    groups["mutation"] = [c for c in checks if "mutation" in c.detail.lower()]
    groups["coverage"] = [c for c in checks if "coverage" in c.detail.lower()]
    return {name: _score(cs) for name, cs in groups.items() if cs}


def confidence(verdict: ACVerdict) -> float:
    """Deterministic confidence in [0, 1] for one AC verdict (docs/11 section 7).

    ``0.4*probe + 0.2*property + 0.2*differential + 0.1*mutation + 0.1*coverage``, but **renormalised
    over the components that are present**: absent methods contribute nothing and do not count against
    the AC, so a probe-only PASS can reach 1.0 (the raw formula would cap it at 0.4). The price is that
    fewer independent methods can score as high as many; the apply gate therefore lists which methods
    ran. A FAIL verdict, or a verdict with no scorable check, scores 0.0.
    """
    if verdict.verdict == "FAIL":
        return 0.0
    comps = confidence_components(verdict)
    total = sum(CONFIDENCE_WEIGHTS[k] for k in comps)
    if total == 0:
        return 0.0
    return round(sum(CONFIDENCE_WEIGHTS[k] * v for k, v in comps.items()) / total, 4)
