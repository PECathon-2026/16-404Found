"""Convergence monitor primitives (docs/11 section 9.3): progress vectors and trends. Pure."""

from __future__ import annotations

import hashlib
from typing import Literal

from devpilot.core.models import (
    ACVerdict,
    Mission,
    ProgressVector,
    TestCaseResult,
    TestOutcome,
    TestRun,
)

Trend = Literal["improving", "flat", "worsening"]

FAILING: frozenset[TestOutcome] = frozenset({TestOutcome.FAILED, TestOutcome.ERROR})


def failing_cases(run: TestRun) -> list[TestCaseResult]:
    """Cases of ``run`` that failed or errored."""
    return [c for c in run.cases if c.outcome in FAILING]


def verifier_fingerprint(av: ACVerdict) -> str:
    """Stable pseudo-fingerprint of a verifier FAIL so repeats of one counterexample are detectable."""
    digest = hashlib.sha1((av.counterexample or av.reasoning).encode(), usedforsecurity=False).hexdigest()
    return f"v:{av.ac_id}:{digest[:6]}"


def progress_vector(mission: Mission, task_key: str, *, tree_sha: str | None = None) -> ProgressVector:
    """Progress of ``task_key`` from the latest TestRun and the latest verdict.

    * ``failing_public``: failing acceptance (public) tests in the latest run;
    * ``failing_fingerprints``: distinct fingerprints of failing tests, plus verifier pseudo-fingerprints;
    * ``regressions``: ``TestRun.regressions``;
    * ``verifier_fails``: ACs the latest verdict marks FAIL among the task's ``acceptance_refs``.

    With ``tree_sha`` only a verdict bound to that tree counts (a verdict on older code says nothing
    about the current attempt).
    """
    run = mission.test_runs[-1] if mission.test_runs else None
    failing = failing_cases(run) if run else []
    sv = mission.verdicts[-1] if mission.verdicts else None
    if sv is not None and tree_sha is not None and sv.diff_sha != tree_sha:
        sv = None
    vfails: list[ACVerdict] = []
    if sv is not None:
        task = mission.tasks.get(task_key)
        refs = set(task.acceptance_refs) if task else set()
        vfails = [v for v in sv.verdict.per_ac if v.verdict == "FAIL" and (not refs or v.ac_id in refs)]
    fps = sorted(
        {c.fingerprint for c in failing if c.fingerprint} | {verifier_fingerprint(v) for v in vfails}
    )
    return ProgressVector(
        failing_public=sum(1 for c in failing if c.is_acceptance),
        failing_fingerprints=fps,
        regressions=len(run.regressions) if run else 0,
        verifier_fails=len(vfails),
    )


def trend(history: list[ProgressVector]) -> Trend:
    """Compare the last two vectors: dominance means improving/worsening, anything else is flat."""
    if len(history) < 2:
        return "flat"
    prev, cur = history[-2], history[-1]
    if cur.dominates(prev):
        return "improving"
    if prev.dominates(cur):
        return "worsening"
    return "flat"


def badness(p: ProgressVector) -> tuple[int, int, int, int]:
    """Lexicographic badness (lower is better), used to pick the best checkpoint."""
    return (p.failing_public + p.regressions, len(p.failing_fingerprints), p.verifier_fails, p.regressions)
