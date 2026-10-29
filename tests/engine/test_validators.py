"""One pass + one fail test per semantic validator, plus registry completeness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine_helpers import make_ac, make_evidence, make_mission, make_spec

from devpilot.core import models as m
from devpilot.core.ports import ModeInvocation
from devpilot.engine import modes
from devpilot.engine.validators import VALIDATORS, ValidationContext, is_test_file, parse_diff_names


def vctx(
    mission: m.Mission | None = None,
    task_key: str | None = "T1",
    attempt: int | None = 1,
    extra: dict[str, Any] | None = None,
    **fns: Any,
) -> ValidationContext:
    inv = ModeInvocation("x", "a#1", task_key=task_key, attempt=attempt, extra_context=extra or {})
    return ValidationContext(mission or make_mission(), inv, **fns)


def names(*n: str):  # type: ignore[no-untyped-def]
    async def diff_names() -> list[str]:
        return list(n)

    return diff_names


def test_every_referenced_validator_is_registered() -> None:
    needed = {v for s in modes.REGISTRY.values() for v in s.validators}
    assert needed <= set(VALIDATORS) and len(needed) == len(VALIDATORS) == 20


def test_helpers() -> None:
    assert is_test_file("tests/unit/x.py") and is_test_file("a/test_x.py") and is_test_file("x_test.py")
    assert (
        is_test_file("web/a.spec.ts")
        and not is_test_file("src/pager.py")
        and not is_test_file("src/latest.py")
    )
    diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\ndiff --git a/b/c.py b/b/c.py\n"
    assert parse_diff_names(diff) == ["a.py", "b/c.py"]


async def run(name: str, out: Any, ctx: ValidationContext) -> list[str]:
    return await VALIDATORS[name](out, ctx)


async def test_paths_exist(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/pager.py").write_text("x")

    async def exists(p: str) -> bool:
        return (tmp_path / p).exists()

    brief = m.RepoBrief(
        summary="s",
        relevant_files=[m.RelevantFile(path="src/pager.py", reason="r")],
        conventions_confirmed=[],
        risks=[],
        baseline_summary="b",
    )
    assert await run("paths_exist", brief, vctx(path_exists=exists)) == []
    brief.relevant_files.append(m.RelevantFile(path="src/ghost.py", reason="r"))
    errs = await run("paths_exist", brief, vctx(path_exists=exists))
    assert len(errs) == 1 and "ghost.py" in errs[0]
    assert await run("paths_exist", brief, vctx()) == []  # no workspace -> skipped


async def test_evidence_exists() -> None:
    ok = m.InvestigationReport(
        question="q", answer="see E-0001", findings=[], locations=[], evidence_ids=["E-0002"]
    )
    assert await run("evidence_exists", ok, vctx()) == []
    bad = m.InvestigationReport(
        question="q", answer="see E-0777", findings=["E-0888"], locations=[], evidence_ids=["E-0001"]
    )
    errs = await run("evidence_exists", bad, vctx())
    assert len(errs) == 2 and "E-0777" in errs[0] + errs[1]
    assert await run("evidence_exists", bad, vctx(ledger_exists=lambda e: e in {"E-0777", "E-0888"})) == []


async def test_ac_ids_sequential() -> None:
    assert await run("ac_ids_sequential", make_spec("AC-1", "AC-2", "AC-3"), vctx()) == []
    assert await run("ac_ids_sequential", make_spec("AC-1", "AC-3"), vctx())
    dupes = make_spec("AC-1", "AC-1")
    assert "duplicate" in (await run("ac_ids_sequential", dupes, vctx()))[0]


def plan_with(refs: list[str], files: list[str] | None = None) -> m.Plan:
    return m.Plan(
        rationale="r",
        tasks=[
            m.TaskDraft(
                key="T1",
                title="t",
                description="d",
                acceptance_refs=refs,
                files_to_touch=files or ["src/pager.py"],
            )
        ],
    )


async def test_plan_covers_all_must_acs() -> None:
    assert await run("plan_covers_all_must_acs", plan_with(["AC-1", "AC-2"]), vctx()) == []
    errs = await run("plan_covers_all_must_acs", plan_with(["AC-1"]), vctx())
    assert len(errs) == 1 and "AC-2" in errs[0]
    mission = make_mission()
    mission.spec = m.MissionSpec(
        restated_request="r",
        objectives=["o"],
        ambiguity=m.Ambiguity(level=m.Level.LOW),
        mission_kind="bugfix",
        acceptance_criteria=[make_ac("AC-1", preserve=True), make_ac("AC-2", priority="should")],
    )
    assert await run("plan_covers_all_must_acs", plan_with(["AC-1"]), vctx(mission)) == []


async def test_plan_paths_plausible(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/pager.py").write_text("x")

    async def exists(p: str) -> bool:
        return (tmp_path / p).exists()

    ctx = vctx(path_exists=exists)
    assert (
        await run("plan_paths_plausible", plan_with(["AC-1"], ["src/pager.py", "src/new.py", "top.py"]), ctx)
        == []
    )
    errs = await run("plan_paths_plausible", plan_with(["AC-1"], ["nowhere/deep/x.py"]), ctx)
    assert len(errs) == 1 and "nowhere/deep" in errs[0]


async def test_revision_has_reason() -> None:
    plan = plan_with(["AC-1"])
    assert await run("revision_has_reason", plan, vctx()) != []  # mission already has a plan
    plan.revised_because = "finding F-1"
    assert await run("revision_has_reason", plan, vctx()) == []
    assert (
        await run(
            "revision_has_reason",
            plan_with(["AC-1"]),
            vctx(m.Mission(id="x", request="r", repo_path="/", workspace_path="/")),
        )
        == []
    )


def dossier(*actions: m.LegalAction) -> m.DecisionDossier:
    return m.DecisionDossier(
        trigger_event_seq=1,
        trigger_summary="t",
        evidence_summaries={},
        task_histories={},
        progress={},
        budget=m.BudgetState(),
        legal_actions=list(actions),
        open_findings=[],
    )


def decision(action: m.Action, target: str | None = "T1") -> m.Decision:
    return m.Decision(
        action=action,
        target=target,
        justification="j",
        cited_evidence=["E-0001"],
        expected_outcome="o",
        confidence=0.5,
        fallback_if_fails=m.Action.ABORT,
    )


async def test_action_is_legal() -> None:
    d = dossier(
        m.LegalAction(action=m.Action.REASSIGN, target="T1", est_tokens=1, est_seconds=1),
        m.LegalAction(action=m.Action.ABORT, est_tokens=0, est_seconds=0),
    )
    ctx = vctx(extra={"dossier": d})
    assert await run("action_is_legal", decision(m.Action.REASSIGN), ctx) == []
    assert await run("action_is_legal", decision(m.Action.ABORT, None), ctx) == []
    errs = await run("action_is_legal", decision(m.Action.REPLAN, None), ctx)
    assert errs and "REASSIGN(T1)" in errs[0]
    assert await run("action_is_legal", decision(m.Action.REASSIGN, "T2"), ctx)
    assert await run("action_is_legal", decision(m.Action.REPLAN), vctx()) == []  # no dossier -> skipped


async def test_no_repeat_failed_strategy() -> None:
    mission = make_mission()
    d = decision(m.Action.RETRY_SAME_AGENT)
    assert await run("no_repeat_failed_strategy", d, vctx(mission)) == []  # fp-aaaa seen once
    mission.tasks["T1"].attempts.append(
        m.Attempt(n=2, mode_id="samurai.rework", agent_id="s", model="m", fingerprints=["fp-aaaa"])
    )
    errs = await run("no_repeat_failed_strategy", d, vctx(mission))
    assert len(errs) == 1 and "fp-aaaa" in errs[0]
    assert await run("no_repeat_failed_strategy", decision(m.Action.REASSIGN), vctx(mission)) == []


def suite(
    path: str = "tests/test_pager.py",
    ac_ids: tuple[str, ...] = ("AC-1", "AC-2"),
    names_: tuple[str, ...] = ("test_a",),
) -> m.AcceptanceSuite:
    return m.AcceptanceSuite(
        tests=[m.AcceptanceTest(ac_id=a, path=path, test_names=list(names_), rationale="r") for a in ac_ids],
        expected_initial_state="red",
    )


async def test_acceptance_files_are_tests_only() -> None:
    ok = vctx(diff_names=names("tests/test_pager.py", "tests/conftest.py"))
    assert await run("acceptance_files_are_tests_only", suite(), ok) == []
    bad = vctx(diff_names=names("tests/test_pager.py", "src/pager.py"))
    errs = await run("acceptance_files_are_tests_only", suite(), bad)
    assert len(errs) == 1 and "src/pager.py" in errs[0]
    assert await run("acceptance_files_are_tests_only", suite("src/pager.py"), vctx())  # suite path itself


async def test_every_must_ac_has_test() -> None:
    assert await run("every_must_ac_has_test", suite(), vctx()) == []
    errs = await run("every_must_ac_has_test", suite(ac_ids=("AC-1",)), vctx())
    assert len(errs) == 1 and "AC-2" in errs[0]
    assert await run("every_must_ac_has_test", suite(names_=()), vctx())


async def test_tests_collect() -> None:
    async def yes(paths: list[str]) -> bool:
        return True

    async def no(paths: list[str]) -> bool:
        return False

    assert await run("tests_collect", suite(), vctx(collect_tests=yes)) == []
    assert await run("tests_collect", suite(), vctx(collect_tests=no))
    assert await run("tests_collect", suite(), vctx()) == []


def triage(fp: str) -> m.TriageReport:
    hyp = m.Hypothesis(statement="s", rank=1, experiment="e")
    return m.TriageReport(
        summary="s",
        items=[
            m.TriageItem(
                nodeid="tests/test_a.py::test_bad",
                fingerprint=fp,
                error_type="AssertionError",
                category="regression",
                hypotheses=[hyp],
                implicated_locations=["src/pager.py:L10"],
                fix_direction="f",
                confidence=0.5,
            )
        ],
    )


async def test_fingerprints_match_runs() -> None:
    assert await run("fingerprints_match_runs", triage("fp-aaaa"), vctx()) == []
    errs = await run("fingerprints_match_runs", triage("fp-zzzz"), vctx())
    assert len(errs) == 1 and "fp-zzzz" in errs[0]
    empty = m.Mission(id="x", request="r", repo_path="/", workspace_path="/")
    assert await run("fingerprints_match_runs", triage("fp-zzzz"), vctx(empty)) == []


def verdict(
    ac_ids: tuple[str, ...],
    v: str = "PASS",
    eids: tuple[str, ...] = ("E-0001",),
    passed: bool = True,
) -> m.VerifierVerdict:
    return m.VerifierVerdict(
        per_ac=[
            m.ACVerdict(
                ac_id=a,
                verdict=v,
                reasoning="r",  # type: ignore[arg-type]
                checks=[
                    m.CheckResult(
                        method=m.VerificationMethod.PROBE, passed=passed, evidence_ids=list(eids), detail="d"
                    )
                ],
            )
            for a in ac_ids
        ],
        test_integrity_ok=True,
        overall="ACCEPT",
    )


async def test_verdict_covers_all_acs() -> None:
    assert await run("verdict_covers_all_acs", verdict(("AC-1", "AC-2")), vctx()) == []
    errs = await run("verdict_covers_all_acs", verdict(("AC-1", "AC-9")), vctx())
    assert any("AC-2" in e for e in errs) and any("AC-9" in e for e in errs)
    assert any(
        "duplicate" in e
        for e in await run("verdict_covers_all_acs", verdict(("AC-1", "AC-1", "AC-2")), vctx())
    )


async def test_pass_requires_execution_evidence() -> None:
    mission = make_mission()
    mission.evidence["E-0003"] = make_evidence("E-0003", m.EvidenceKind.DIFF)
    assert await run("pass_requires_execution_evidence", verdict(("AC-1",)), vctx(mission)) == []  # TEST_RUN
    assert await run("pass_requires_execution_evidence", verdict(("AC-1",), eids=("E-0003",)), vctx(mission))
    assert await run("pass_requires_execution_evidence", verdict(("AC-1",), eids=("E-0999",)), vctx(mission))
    assert await run("pass_requires_execution_evidence", verdict(("AC-1",), passed=False), vctx(mission))
    assert (
        await run("pass_requires_execution_evidence", verdict(("AC-1",), v="FAIL", eids=()), vctx(mission))
        == []
    )


def report(**kw: Any) -> m.ChangeReport:
    base: dict[str, Any] = {
        "status": "done",
        "hypothesis": "h",
        "approach": "a",
        "files_changed": ["src/pager.py"],
    }
    base.update(kw)
    return m.ChangeReport(**base)


async def test_files_changed_matches_diff() -> None:
    assert await run("files_changed_matches_diff", report(), vctx(diff_names=names("src/pager.py"))) == []
    assert (
        await run(
            "files_changed_matches_diff",
            report(files_changed=["./src/pager.py"]),
            vctx(diff_names=names("src/pager.py")),
        )
        == []
    )
    e1 = await run(
        "files_changed_matches_diff", report(), vctx(diff_names=names("src/pager.py", "src/other.py"))
    )
    assert len(e1) == 1 and "omits" in e1[0]
    e2 = await run(
        "files_changed_matches_diff",
        report(files_changed=["src/pager.py", "x.py"]),
        vctx(diff_names=names("src/pager.py")),
    )
    assert len(e2) == 1 and "not in the diff" in e2[0]
    assert await run("files_changed_matches_diff", report(), vctx()) == []


async def test_within_file_locks() -> None:
    ok = vctx(diff_names=names("src/pager.py", "tests/test_pager.py"))
    assert await run("within_file_locks", report(), ok) == []
    errs = await run("within_file_locks", report(), vctx(diff_names=names("src/pager.py", "src/db.py")))
    assert len(errs) == 1 and "src/db.py" in errs[0]
    assert await run("within_file_locks", report(), vctx(task_key=None, diff_names=names("x.py"))) == []


async def test_rework_states_difference() -> None:
    assert await run("rework_states_difference", report(), vctx(attempt=1)) == []
    assert await run("rework_states_difference", report(), vctx(attempt=2))
    assert await run("rework_states_difference", report(differs_from_previous="  "), vctx(attempt=2))
    assert await run("rework_states_difference", report(differs_from_previous="ceil"), vctx(attempt=2)) == []


async def test_winner_passed_gates() -> None:
    def score(name: str, ok: bool) -> m.CandidateScore:
        return m.CandidateScore(
            candidate=name,
            gates_passed=ok,
            gate_failures=[] if ok else ["lint"],
            public_pass_rate=1.0,
            regressions=0,
            mutation_kill_rate=None,
            lint_issues=0,
            diff_lines=1,
            convention_similarity=1.0,
            weighted=1.0,
        )

    ctx = vctx(extra={"candidate_scores": [score("cand-A", True), score("cand-B", False)]})
    mk = lambda w: m.TournamentResult(winner=w, rationale="r")  # noqa: E731
    assert await run("winner_passed_gates", mk("cand-A"), ctx) == []
    assert "lint" in (await run("winner_passed_gates", mk("cand-B"), ctx))[0]
    assert "not a candidate" in (await run("winner_passed_gates", mk("cand-Z"), ctx))[0]
    assert await run("winner_passed_gates", mk("cand-B"), vctx()) == []


def finding(
    sev: str = "blocker", proven: bool = True, eids: tuple[str, ...] = ("E-0001",)
) -> m.ReviewFinding:
    return m.ReviewFinding(
        severity=sev,
        lens=m.ReviewLens.CORRECTNESS,
        location="a.py:L1",  # type: ignore[arg-type]
        description="d",
        suggestion="s",
        evidence_ids=list(eids),
        proven=proven,
    )


async def test_unproven_blockers_downgraded() -> None:
    def rep(*f: m.ReviewFinding) -> m.ReviewReport:
        return m.ReviewReport(lens=m.ReviewLens.CORRECTNESS, findings=list(f), decision="request_changes")

    assert (
        await run("unproven_blockers_downgraded", rep(finding(), finding("minor", False, ())), vctx()) == []
    )
    assert await run("unproven_blockers_downgraded", rep(finding(proven=False)), vctx())
    assert await run("unproven_blockers_downgraded", rep(finding("major", True, ())), vctx())


async def test_introduced_flag_matches_diff() -> None:
    async def hunks() -> list[str]:
        return ["src/pager.py:L10-L20"]

    def rep(loc: str, introduced: bool) -> m.SecurityReport:
        return m.SecurityReport(
            findings=[
                m.SecurityFinding(
                    severity="low",
                    source="llm",
                    introduced_by_change=introduced,
                    location=loc,
                    description="d",
                    remediation="r",
                )
            ],
            scanners_run=[],
            scanners_unavailable=[],
            decision="pass",
        )

    ctx = vctx(hunk_paths=hunks)
    assert await run("introduced_flag_matches_diff", rep("src/pager.py:L12", True), ctx) == []
    assert await run("introduced_flag_matches_diff", rep("src/pager.py:L18-L25", True), ctx) == []
    assert await run("introduced_flag_matches_diff", rep("src/pager.py:L50", False), ctx) == []
    assert await run("introduced_flag_matches_diff", rep("src/other.py:L12", False), ctx) == []
    assert await run("introduced_flag_matches_diff", rep("src/pager.py:L50", True), ctx)
    assert await run("introduced_flag_matches_diff", rep("src/pager.py:L12", False), ctx)
    assert await run("introduced_flag_matches_diff", rep("src/pager.py:L50", True), vctx()) == []
