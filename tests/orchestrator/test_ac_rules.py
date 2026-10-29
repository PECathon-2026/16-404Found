"""ac_status (docs/06 section 6) and the deterministic confidence formula (docs/11 section 7)."""

from __future__ import annotations

import pytest

from devpilot.core import models as m
from devpilot.orchestrator import ac_rules

SHA = "tree9"


def ac(ac_id: str = "AC-1", methods: list[m.VerificationMethod] | None = None) -> m.AcceptanceCriterion:
    return m.AcceptanceCriterion(
        id=ac_id,
        given="g",
        when="w",
        then="t",
        verification_methods=methods or [m.VerificationMethod.ACCEPTANCE_TEST],
        preserves_existing_behaviour=True,
    )


def evidence(
    eid: str,
    *,
    sha: str = SHA,
    kind: m.EvidenceKind = m.EvidenceKind.TEST_RUN,
    exit_code: int | None = 0,
    ac_ids: list[str] | None = None,
) -> m.Evidence:
    return m.Evidence(
        id=eid,
        kind=kind,
        tool="test.run",
        agent_id="system",
        workspace_ref="main",
        workspace_sha=sha,
        summary="s",
        log_path="l",
        sha256="0" * 64,
        exit_code=exit_code,
        ac_ids=["AC-1"] if ac_ids is None else ac_ids,
    )


def verdict(v: str = "PASS", ac_id: str = "AC-1", checks: list[m.CheckResult] | None = None) -> m.ACVerdict:
    return m.ACVerdict(ac_id=ac_id, verdict=v, checks=checks or [], reasoning="r")  # type: ignore[arg-type]


def scored(per_ac: list[m.ACVerdict], sha: str = SHA, sid: str = "V-1") -> m.ScoredVerdict:
    return m.ScoredVerdict(
        id=sid,
        diff_sha=sha,
        confidence_by_ac={},
        verdict=m.VerifierVerdict(per_ac=per_ac, test_integrity_ok=True, overall="ACCEPT"),
    )


def mission(*evs: m.Evidence, verdicts: list[m.ScoredVerdict] | None = None) -> m.Mission:
    mi = m.Mission(id="M", request="r", repo_path="/r", workspace_path="/w")
    mi.evidence = {e.id: e for e in evs}
    mi.verdicts = verdicts or []
    return mi


def test_verified_needs_passing_evidence_on_the_final_sha_and_a_pass_verdict() -> None:
    mi = mission(evidence("E-0001"), verdicts=[scored([verdict("PASS")])])
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.VERIFIED


def test_accepts_an_acstate() -> None:
    mi = mission(evidence("E-0001"), verdicts=[scored([verdict("PASS")])])
    assert ac_rules.ac_status(m.ACState(ac=ac()), mi, SHA) == m.ACStatus.VERIFIED


@pytest.mark.parametrize(
    "ev",
    [
        evidence("E-0001", sha="older"),  # evidence from another tree
        evidence("E-0001", exit_code=1),  # failing run
        evidence("E-0001", exit_code=None),
        evidence("E-0001", kind=m.EvidenceKind.TOOL_OUTPUT),  # not execution evidence
        evidence("E-0001", kind=m.EvidenceKind.DIFF),
        evidence("E-0001", ac_ids=["AC-2"]),  # bears on another AC
    ],
)
def test_pass_verdict_without_proper_evidence_is_not_verified(ev: m.Evidence) -> None:
    mi = mission(ev, verdicts=[scored([verdict("PASS")])])
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.UNVERIFIED


@pytest.mark.parametrize(
    "kind",
    [
        m.EvidenceKind.TEST_RUN,
        m.EvidenceKind.PROBE_RUN,
        m.EvidenceKind.PROPERTY_RUN,
        m.EvidenceKind.DIFFERENTIAL_RUN,
    ],
)
def test_every_execution_kind_counts(kind: m.EvidenceKind) -> None:
    mi = mission(evidence("E-0001", kind=kind), verdicts=[scored([verdict("PASS")])])
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.VERIFIED


def test_evidence_cited_by_the_verdict_counts_even_if_untagged() -> None:
    chk = m.CheckResult(method=m.VerificationMethod.PROBE, passed=True, evidence_ids=["E-0007"], detail="p")
    mi = mission(
        evidence("E-0007", ac_ids=[], kind=m.EvidenceKind.PROBE_RUN),
        verdicts=[scored([verdict("PASS", checks=[chk])])],
    )
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.VERIFIED
    assert ac_rules.supporting_evidence_ids(mi, "AC-1", SHA) == ["E-0007"]


def test_verdict_for_another_diff_is_stale() -> None:
    mi = mission(evidence("E-0001"), verdicts=[scored([verdict("PASS")], sha="older")])
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.UNVERIFIED


def test_latest_verdict_for_the_diff_wins() -> None:
    mi = mission(
        evidence("E-0001"),
        verdicts=[scored([verdict("FAIL")], sid="V-1"), scored([verdict("PASS")], sid="V-2")],
    )
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.VERIFIED
    mi.verdicts.reverse()
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.FAILED


def test_fail_verdict_is_failed_regardless_of_evidence() -> None:
    mi = mission(evidence("E-0001"), verdicts=[scored([verdict("FAIL")])])
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.FAILED


def test_inconclusive_is_unverified() -> None:
    mi = mission(evidence("E-0001"), verdicts=[scored([verdict("INCONCLUSIVE")])])
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.UNVERIFIED


def test_manual_only_ac_stays_unverified() -> None:
    mi = mission()
    assert ac_rules.ac_status(ac(methods=[m.VerificationMethod.MANUAL]), mi, SHA) == m.ACStatus.UNVERIFIED


def test_claimed_when_only_an_agent_asserts_it() -> None:
    mi = mission()
    mi.tasks["T1"] = m.Task(
        id="t",
        key="T1",
        title="t",
        description="d",
        acceptance_refs=["AC-1"],
        files_to_touch=[],
        depends_on=[],
        may_edit_tests=False,
        risk=m.Level.LOW,
        plan_version=1,
    )
    mi.submissions["S-1"] = m.Submission(
        id="S-1",
        mode_id="samurai.implement",
        agent_id="samurai#1",
        model="x",
        task_key="T1",
        output_type="ChangeReport",
        payload={"status": "done"},
    )
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.CLAIMED
    assert ac_rules.ac_status(ac("AC-2"), mi, SHA) == m.ACStatus.UNVERIFIED  # not in the task's refs
    mi.submissions["S-1"].payload["status"] = "blocked"
    assert ac_rules.ac_status(ac(), mi, SHA) == m.ACStatus.UNVERIFIED


# ------------------------------------------------------------------------------ confidence


def check(
    method: m.VerificationMethod, passed: bool = True, metric: float | None = None, detail: str = "d"
) -> m.CheckResult:
    return m.CheckResult(method=method, passed=passed, evidence_ids=[], detail=detail, metric=metric)


def conf(checks: list[m.CheckResult], v: str = "PASS") -> float:
    return ac_rules.confidence(verdict(v, checks=checks))


def test_probe_only_pass_reaches_one() -> None:
    assert conf([check(m.VerificationMethod.PROBE)]) == 1.0


def test_probe_only_fail_check_is_zero() -> None:
    assert conf([check(m.VerificationMethod.PROBE, passed=False)]) == 0.0


def test_full_weighting_matches_the_formula() -> None:
    checks = [
        check(m.VerificationMethod.PROBE),
        check(m.VerificationMethod.PROPERTY, passed=False),
        check(m.VerificationMethod.DIFFERENTIAL),
        check(m.VerificationMethod.STATIC_CHECK, metric=0.5, detail="mutation kill rate"),
        check(m.VerificationMethod.STATIC_CHECK, metric=0.8, detail="changed-line coverage"),
    ]
    # 0.4*1 + 0.2*0 + 0.2*1 + 0.1*0.5 + 0.1*0.8 = 0.73 (all five present: no renormalisation)
    assert conf(checks) == pytest.approx(0.73)


def test_renormalises_over_present_methods() -> None:
    # probe pass (0.4) + differential fail (0.0): 0.4 / 0.6
    assert conf(
        [check(m.VerificationMethod.PROBE), check(m.VerificationMethod.DIFFERENTIAL, passed=False)]
    ) == pytest.approx(0.6667, abs=1e-4)
    # property + differential only, both pass: absent probe does not count against the AC
    assert conf([check(m.VerificationMethod.PROPERTY), check(m.VerificationMethod.DIFFERENTIAL)]) == 1.0


def test_multiple_checks_of_one_method_are_averaged() -> None:
    assert conf([check(m.VerificationMethod.PROBE), check(m.VerificationMethod.PROBE, passed=False)]) == 0.5


def test_metric_overrides_pass_flag_and_is_clamped() -> None:
    assert conf([check(m.VerificationMethod.PROBE, metric=0.25)]) == 0.25
    assert conf([check(m.VerificationMethod.PROBE, metric=7.0)]) == 1.0
    assert conf([check(m.VerificationMethod.PROBE, metric=-1.0)]) == 0.0


def test_executed_tests_stand_in_for_a_missing_probe() -> None:
    assert conf([check(m.VerificationMethod.ACCEPTANCE_TEST)]) == 1.0
    # but a real probe takes precedence over the stand-in
    assert (
        conf([check(m.VerificationMethod.ACCEPTANCE_TEST), check(m.VerificationMethod.PROBE, passed=False)])
        == 0.0
    )


def test_no_scorable_checks_or_fail_verdict_is_zero() -> None:
    assert conf([]) == 0.0
    assert conf([check(m.VerificationMethod.MANUAL)]) == 0.0
    assert conf([check(m.VerificationMethod.PROBE)], v="FAIL") == 0.0


def test_weights_sum_to_one() -> None:
    assert sum(ac_rules.CONFIDENCE_WEIGHTS.values()) == pytest.approx(1.0)
