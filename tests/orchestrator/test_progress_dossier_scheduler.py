"""Progress vectors / trend, the decision dossier and the scheduler: all pure."""

from __future__ import annotations

from orch_helpers import make_run

from devpilot.core import models as m
from devpilot.core.events import Event, EventType
from devpilot.orchestrator import dossier, progress, scheduler


def mission_with_run(run: m.TestRun | None = None, verdict: m.ScoredVerdict | None = None) -> m.Mission:
    mi = m.Mission(id="M", request="r", repo_path="/r", workspace_path="/w")
    mi.tasks["T1"] = task("T1", refs=["AC-1", "AC-2"])
    if run:
        mi.test_runs.append(run)
    if verdict:
        mi.verdicts.append(verdict)
    return mi


def task(
    key: str,
    *,
    deps: list[str] | None = None,
    files: list[str] | None = None,
    status: m.TaskStatus = m.TaskStatus.PENDING,
    refs: list[str] | None = None,
) -> m.Task:
    return m.Task(
        id=f"t-{key}",
        key=key,
        title=key,
        description="d",
        acceptance_refs=refs or ["AC-1"],
        files_to_touch=files if files is not None else [f"{key}.py"],
        depends_on=deps or [],
        may_edit_tests=False,
        risk=m.Level.LOW,
        plan_version=1,
        status=status,
    )


# ------------------------------------------------------------------------------ progress


def test_progress_vector_from_the_latest_run() -> None:
    mi = mission_with_run(
        make_run("full", n=1, red=True, fp="fpX", regression=True, failing=("test_ac1", "test_ac2"))
    )
    pv = progress.progress_vector(mi, "T1")
    assert pv == m.ProgressVector(
        failing_public=2, failing_fingerprints=["fpX"], regressions=2, verifier_fails=0
    )


def test_only_acceptance_tests_count_as_failing_public() -> None:
    run = make_run("full", n=1, red=True)
    run.cases[1] = run.cases[1].model_copy(update={"is_acceptance": False})
    assert progress.progress_vector(mission_with_run(run), "T1").failing_public == 0


def test_green_run_is_all_zero_and_no_run_is_all_zero() -> None:
    assert progress.progress_vector(mission_with_run(make_run("full", n=1)), "T1") == m.ProgressVector(
        failing_public=0, failing_fingerprints=[], regressions=0, verifier_fails=0
    )
    assert progress.progress_vector(mission_with_run(), "T1").failing_public == 0


def scored(sha: str, *verdicts: tuple[str, str, str | None]) -> m.ScoredVerdict:
    return m.ScoredVerdict(
        id="V-1",
        diff_sha=sha,
        confidence_by_ac={},
        verdict=m.VerifierVerdict(
            per_ac=[
                m.ACVerdict(ac_id=a, verdict=v, checks=[], reasoning="r", counterexample=c)
                for a, v, c in verdicts
            ],  # type: ignore[arg-type]
            test_integrity_ok=True,
            overall="REJECT",
        ),
    )


def test_verifier_fails_and_pseudo_fingerprints() -> None:
    v = scored("s1", ("AC-1", "PASS", None), ("AC-2", "FAIL", "total=0"))
    pv = progress.progress_vector(mission_with_run(make_run("full", n=1), v), "T1")
    assert (
        pv.verifier_fails == 1
        and len(pv.failing_fingerprints) == 1
        and pv.failing_fingerprints[0].startswith("v:AC-2:")
    )
    # the same counterexample yields the same fingerprint (so repeats are detectable), another one differs
    pv2 = progress.progress_vector(
        mission_with_run(make_run("full", n=1), scored("s2", ("AC-2", "FAIL", "total=0"))), "T1"
    )
    pv3 = progress.progress_vector(
        mission_with_run(make_run("full", n=1), scored("s2", ("AC-2", "FAIL", "total=5"))), "T1"
    )
    assert pv2.failing_fingerprints == pv.failing_fingerprints != pv3.failing_fingerprints


def test_verdict_is_ignored_when_bound_to_another_tree() -> None:
    mi = mission_with_run(make_run("full", n=1), scored("old", ("AC-2", "FAIL", "x")))
    assert progress.progress_vector(mi, "T1").verifier_fails == 1  # latest verdict, no tree given
    assert progress.progress_vector(mi, "T1", tree_sha="new").verifier_fails == 0
    assert progress.progress_vector(mi, "T1", tree_sha="old").verifier_fails == 1


def test_verifier_fails_are_limited_to_the_tasks_acs() -> None:
    mi = mission_with_run(make_run("full", n=1), scored("s", ("AC-9", "FAIL", "x")))
    assert progress.progress_vector(mi, "T1").verifier_fails == 0


def pvec(public: int, fps: int = 0, reg: int = 0, vf: int = 0) -> m.ProgressVector:
    return m.ProgressVector(
        failing_public=public,
        failing_fingerprints=[f"f{i}" for i in range(fps)],
        regressions=reg,
        verifier_fails=vf,
    )


def test_trend() -> None:
    assert progress.trend([]) == "flat"
    assert progress.trend([pvec(2)]) == "flat"
    assert progress.trend([pvec(2, 1), pvec(1, 1)]) == "improving"
    assert progress.trend([pvec(1, 1), pvec(2, 1)]) == "worsening"
    assert progress.trend([pvec(1, 1), pvec(1, 1)]) == "flat"  # identical: no strict improvement
    assert progress.trend([pvec(2, 0), pvec(1, 1)]) == "flat"  # trade-off: neither dominates
    assert progress.trend([pvec(5), pvec(3), pvec(4)]) == "worsening"  # only the last two matter


def test_badness_orders_progress() -> None:
    assert progress.badness(pvec(0)) < progress.badness(pvec(1)) < progress.badness(pvec(1, 1, 1))


# ------------------------------------------------------------------------------ dossier


def test_dossier_cites_trigger_and_open_finding_evidence() -> None:
    mi = mission_with_run()
    for eid in ("E-0001", "E-0002", "E-0003"):
        mi.evidence[eid] = m.Evidence(
            id=eid,
            kind=m.EvidenceKind.TEST_RUN,
            tool="t",
            agent_id="a",
            workspace_ref="main",
            workspace_sha="s",
            summary=f"summary of {eid}",
            log_path="l",
            sha256="0" * 64,
        )
    mi.findings["F-1"] = m.Finding(
        id="F-1",
        source_agent="sentinel",
        source_mode="sentinel.triage",
        kind="triage",
        severity=m.Severity.HIGH,
        summary="s",
        payload={},
        routed_to="T1",
        evidence_ids=["E-0002"],
    )
    mi.findings["F-2"] = m.Finding(
        id="F-2",
        source_agent="sentinel",
        source_mode="sentinel.triage",
        kind="triage",
        severity=m.Severity.HIGH,
        summary="s",
        payload={},
        routed_to="T1",
        evidence_ids=["E-0003"],
        status="addressed",
    )
    ev = Event(
        seq=17,
        mission_id="M",
        type=EventType.TEST_RUN,
        actor="system",
        summary="full tests red",
        payload={"test_run": {"evidence_id": "E-0001"}, "note": "also E-9999 which is unknown"},
    )
    legal = [m.LegalAction(action=m.Action.STOP_PARTIAL, est_tokens=0, est_seconds=0)]
    d = dossier.build_dossier(mi, ev, "T1", legal)
    assert d.trigger_event_seq == 17 and d.trigger_summary == "full tests red"
    assert d.evidence_summaries == {
        "E-0001": "summary of E-0001",
        "E-0002": "summary of E-0002",
    }  # not E-0003 (addressed), not E-9999
    assert d.open_findings == ["F-1"]
    assert d.legal_actions == legal
    assert list(d.task_histories) == ["T1"] and list(d.progress) == ["T1"]


def test_dossier_progress_and_budget_override() -> None:
    mi = mission_with_run()
    mi.tasks["T2"] = task("T2")
    mi.tasks["T1"].attempts = [
        m.Attempt(n=1, mode_id="samurai.implement", agent_id="s#1", model="x", progress=pvec(2, 1)),
        m.Attempt(n=2, mode_id="samurai.rework", agent_id="s#1", model="x"),
    ]
    ev = Event(seq=1, mission_id="M", type=EventType.STATE_CHANGED, actor="system", payload={})
    budget = m.BudgetState(fix_cycles=3)
    d = dossier.build_dossier(mi, ev, "T2", [], budget=budget)
    assert list(d.task_histories) == ["T2", "T1"]  # the task being decided about comes first
    assert d.progress["T1"] == [pvec(2, 1)] and d.progress["T2"] == []
    assert d.budget.fix_cycles == 3 and mi.budget.fix_cycles == 0
    assert d.trigger_summary == "STATE_CHANGED"
    assert m.DecisionDossier.model_validate(d.model_dump(mode="json")) == d  # JSON-safe for extra_context


# ------------------------------------------------------------------------------ scheduler


def tmission(*tasks: m.Task) -> m.Mission:
    mi = m.Mission(id="M", request="r", repo_path="/r", workspace_path="/w")
    mi.tasks = {t.key: t for t in tasks}
    return mi


def test_ready_tasks_require_done_dependencies() -> None:
    mi = tmission(
        task("T1", status=m.TaskStatus.DONE),
        task("T2", deps=["T1"]),
        task("T3", deps=["T2"]),
        task("T4", status=m.TaskStatus.READY),
        task("T5", status=m.TaskStatus.IN_PROGRESS),
        task("T6", status=m.TaskStatus.CANCELLED),
    )
    assert [t.key for t in scheduler.ready_tasks(mi)] == ["T2", "T4"]


def test_a_dependency_that_is_not_done_or_missing_blocks() -> None:
    mi = tmission(task("T1", status=m.TaskStatus.TESTING), task("T2", deps=["T1"]), task("T3", deps=["T0"]))
    assert scheduler.ready_tasks(mi) == []


def test_batch_is_greedy_disjoint_and_capped() -> None:
    ts = [
        task("T1", files=["a.py"]),
        task("T2", files=["a.py", "b.py"]),
        task("T3", files=["c.py"]),
        task("T4", files=["d.py"]),
    ]
    assert [t.key for t in scheduler.batch(ts, 3)] == ["T1", "T3", "T4"]
    assert [t.key for t in scheduler.batch(ts, 2)] == ["T1", "T3"]
    assert [t.key for t in scheduler.batch(ts, 1)] == ["T1"]
    assert [t.key for t in scheduler.batch(ts, 0)] == ["T1"]  # clamped: progress is always possible
    assert scheduler.batch([], 3) == []


def test_tasks_without_files_never_conflict() -> None:
    ts = [task("T1", files=[]), task("T2", files=[]), task("T3", files=["x.py"])]
    assert [t.key for t in scheduler.batch(ts, 5)] == ["T1", "T2", "T3"]
