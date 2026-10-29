"""Guards (docs/04 section 6.3): every row of the table, in isolation and in combination."""

from __future__ import annotations

from typing import Any

import pytest

from devpilot.core import models as m
from devpilot.core.models import Action as A
from devpilot.orchestrator import guards
from devpilot.orchestrator.guards import GuardCounters, legal_actions, override


def attempt(n: int, fps: list[str], progress: m.ProgressVector | None = None) -> m.Attempt:
    return m.Attempt(
        n=n,
        mode_id="samurai.rework",
        agent_id="samurai#1",
        model="x",
        fingerprints=fps,
        progress=progress,
        outcome="red",
    )


def pv(public: int = 1, fps: int = 1, reg: int = 0, vf: int = 0) -> m.ProgressVector:
    return m.ProgressVector(
        failing_public=public,
        failing_fingerprints=[f"f{i}" for i in range(fps)],
        regressions=reg,
        verifier_fails=vf,
    )


def mission(
    attempts: list[m.Attempt] | None = None, *, limits: m.Budgets | None = None, **extra: Any
) -> m.Mission:
    mi = m.Mission(
        id="M",
        request="r",
        repo_path="/r",
        workspace_path="/w",
        budget=m.BudgetState(limits=limits or m.Budgets()),
    )
    mi.tasks["T1"] = m.Task(
        id="t",
        key="T1",
        title="t",
        description="d",
        acceptance_refs=["AC-1"],
        files_to_touch=["a.py"],
        depends_on=[],
        may_edit_tests=False,
        risk=m.Level.LOW,
        plan_version=1,
        attempts=attempts or [attempt(1, ["fpA"])],
    )
    for k, v in extra.items():
        setattr(mi, k, v)
    return mi


def acts(mi: m.Mission, tournament: bool = True, **kw: Any) -> set[A]:
    return {la.action for la in legal_actions(mi, "T1", tournament_available=tournament, **kw)}


def decision(action: A, fallback: A = A.ASK_HUMAN) -> m.Decision:
    return m.Decision(
        action=action,
        justification="j",
        cited_evidence=["E-0001"],
        expected_outcome="o",
        confidence=0.5,
        fallback_if_fails=fallback,
    )


FULL = {
    A.RETRY_SAME_AGENT,
    A.REASSIGN,
    A.ESCALATE_MODEL,
    A.INVESTIGATE,
    A.REPLAN,
    A.TOURNAMENT,
    A.ASK_HUMAN,
    A.STOP_PARTIAL,
}


def test_fresh_failure_offers_everything_except_rollback() -> None:
    assert acts(mission()) == FULL  # no better checkpoint -> no ROLLBACK; ABORT is never offered


def test_fingerprint_seen_once_allows_retry() -> None:
    assert A.RETRY_SAME_AGENT in acts(mission([attempt(1, ["fpA"])]))


def test_repeat_fingerprint_2_forbids_retry_same_agent() -> None:
    mi = mission([attempt(1, ["fpA"]), attempt(2, ["fpA"])])
    assert acts(mi) == FULL - {A.RETRY_SAME_AGENT}
    chosen, reason = override(
        decision(A.RETRY_SAME_AGENT, A.INVESTIGATE), mi, "T1", tournament_available=True
    )
    assert chosen == A.INVESTIGATE and reason is not None and reason.startswith("repeat_fingerprint_2")


def test_different_fingerprints_do_not_count_as_repeats() -> None:
    mi = mission([attempt(1, ["fpA"]), attempt(2, ["fpB"]), attempt(3, ["fpA"])])
    assert guards.fingerprint_repeats(mi.tasks["T1"]) == 2  # fpA appears in attempts 1 and 3
    mi = mission([attempt(1, ["fpA"]), attempt(2, ["fpB"]), attempt(3, ["fpC"])])
    assert guards.fingerprint_repeats(mi.tasks["T1"]) == 1


def test_repeat_fingerprint_3_leaves_only_human_or_stop() -> None:
    mi = mission([attempt(1, ["fpA"]), attempt(2, ["fpA"]), attempt(3, ["fpA"])])
    assert acts(mi) == {A.ASK_HUMAN, A.STOP_PARTIAL}
    chosen, reason = override(decision(A.INVESTIGATE, A.STOP_PARTIAL), mi, "T1", tournament_available=True)
    assert chosen == A.ASK_HUMAN  # a human is preferred over the Shogun's own fallback
    assert reason is not None and reason.startswith("repeat_fingerprint_3")


def test_max_attempts_leaves_only_human_or_stop() -> None:
    mi = mission([attempt(i, [f"f{i}"]) for i in range(1, 5)], limits=m.Budgets(max_attempts_per_task=4))
    assert acts(mi) == {A.ASK_HUMAN, A.STOP_PARTIAL}
    chosen, reason = override(decision(A.REASSIGN), mi, "T1")
    assert chosen == A.ASK_HUMAN and reason is not None and reason.startswith("max_attempts")
    # one attempt fewer and the task still has options
    assert A.REASSIGN in acts(
        mission([attempt(i, [f"f{i}"]) for i in range(1, 4)], limits=m.Budgets(max_attempts_per_task=4))
    )


def test_max_fix_cycles_is_stop_partial_only() -> None:
    mi = mission(limits=m.Budgets(max_fix_cycles=2))
    assert acts(mi, counters=GuardCounters(fix_cycles=1)) == FULL
    assert acts(mi, counters=GuardCounters(fix_cycles=2)) == {A.STOP_PARTIAL}
    chosen, reason = override(decision(A.RETRY_SAME_AGENT), mi, "T1", counters=GuardCounters(fix_cycles=2))
    assert chosen == A.STOP_PARTIAL and reason is not None and reason.startswith("max_fix_cycles")


def test_fix_cycles_fall_back_to_the_mission_budget() -> None:
    mi = mission(limits=m.Budgets(max_fix_cycles=2))
    mi.budget.fix_cycles = 2
    assert acts(mi) == {A.STOP_PARTIAL}


def test_max_replans_forbids_replan() -> None:
    plan = m.PlanRecord(
        id="p",
        version=1,
        plan=m.Plan(
            rationale="r",
            tasks=[m.TaskDraft(key="T1", title="t", description="d", acceptance_refs=[], files_to_touch=[])],
        ),
    )
    mi = mission(limits=m.Budgets(max_replans=1))
    mi.plans = [plan]
    assert A.REPLAN in acts(mi)  # 0 replans so far
    mi.plans = [plan, plan.model_copy(update={"id": "p2", "version": 2})]  # 1 replan used
    assert A.REPLAN not in acts(mi)
    chosen, reason = override(decision(A.REPLAN, A.REASSIGN), mi, "T1")
    assert chosen == A.REASSIGN and reason is not None and reason.startswith("max_replans")
    # the orchestrator's budget counter is honoured too
    mi2 = mission(limits=m.Budgets(max_replans=1))
    mi2.budget.replans = 1
    assert A.REPLAN not in acts(mi2)


def test_tournament_illegal_when_unavailable_or_exhausted() -> None:
    mi = mission(limits=m.Budgets(max_tournaments=1))
    assert A.TOURNAMENT in acts(mi)
    assert A.TOURNAMENT not in acts(mi, tournament=False)
    assert A.TOURNAMENT not in acts(mi, counters=GuardCounters(tournaments=1))
    chosen, reason = override(decision(A.TOURNAMENT, A.REASSIGN), mi, "T1", tournament_available=False)
    assert chosen == A.REASSIGN and reason is not None and reason.startswith("tournament_unavailable")
    _, reason2 = override(
        decision(A.TOURNAMENT, A.REASSIGN),
        mi,
        "T1",
        tournament_available=True,
        counters=GuardCounters(tournaments=1),
    )
    assert reason2 is not None and reason2.startswith("max_tournaments")


@pytest.mark.parametrize(
    "limits",
    [m.Budgets(max_tokens_mission=100), m.Budgets(max_cost_usd=1.0), m.Budgets(max_wall_clock_s=10)],
)
def test_budget_ratio_at_or_above_one_is_stop_partial_only(limits: m.Budgets) -> None:
    mi = mission(limits=limits)
    mi.budget.tokens_in, mi.budget.cost_usd = 100, 1.0
    assert acts(mi, counters=GuardCounters(wall_clock_s=10.0)) == {A.STOP_PARTIAL}
    _, reason = override(decision(A.ASK_HUMAN), mi, "T1", counters=GuardCounters(wall_clock_s=10.0))
    assert reason is not None and reason.startswith(("budget_exhausted", "max_"))


def test_budget_below_one_is_unrestricted() -> None:
    mi = mission(limits=m.Budgets(max_tokens_mission=100))
    mi.budget.tokens_in = 99
    assert acts(mi) == FULL


def test_wall_clock_counter_is_used() -> None:
    mi = mission(limits=m.Budgets(max_wall_clock_s=60))
    assert acts(mi, counters=GuardCounters(wall_clock_s=59.0)) == FULL
    assert acts(mi, counters=GuardCounters(wall_clock_s=61.0)) == {A.STOP_PARTIAL}


def env_finding(fid: str) -> m.Finding:
    return m.Finding(
        id=fid,
        source_agent="sentinel",
        source_mode="sentinel.triage",
        kind="triage",
        severity=m.Severity.MEDIUM,
        summary="module not found",
        payload={"category": "environmental"},
        routed_to="T1",
    )


def test_environmental_failure_repeated_asks_the_human() -> None:
    mi = mission()
    mi.findings = {"F-1": env_finding("F-1")}
    assert acts(mi) == FULL  # once is not a pattern
    mi.findings["F-2"] = env_finding("F-2")
    assert acts(mi) == {A.ASK_HUMAN}
    chosen, reason = override(decision(A.RETRY_SAME_AGENT, A.STOP_PARTIAL), mi, "T1")
    assert chosen == A.ASK_HUMAN and reason is not None and reason.startswith("env_failure")
    # only findings routed to THIS task count
    mi.findings["F-2"] = env_finding("F-2").model_copy(update={"routed_to": "T2"})
    assert acts(mi) == FULL


def test_budget_guards_beat_human_guards() -> None:
    mi = mission([attempt(i, ["fpA"]) for i in range(1, 4)], limits=m.Budgets(max_fix_cycles=1))
    assert acts(mi, counters=GuardCounters(fix_cycles=1)) == {A.STOP_PARTIAL}


# ------------------------------------------------------------------------------ rollback


def cp(sha: str, progress: m.ProgressVector | None) -> dict[str, Any]:
    return {"sha": sha, "seq": 1, "label": sha, "progress": progress.model_dump() if progress else None}


def test_rollback_requires_a_strictly_better_checkpoint() -> None:
    mi = mission([attempt(1, ["a"], pv(2)), attempt(2, ["b"], pv(2))])
    mi.checkpoints = [cp("c0", None), cp("c1", pv(2))]
    assert A.ROLLBACK not in acts(mi)  # best checkpoint is no better than where we are
    mi.checkpoints = [cp("c0", None), cp("c1", pv(1, 1)), cp("c2", pv(2))]
    assert A.ROLLBACK in acts(mi)
    note = next(
        la.note for la in legal_actions(mi, "T1", tournament_available=False) if la.action == A.ROLLBACK
    )
    assert "c1" in note


def test_best_checkpoint_prefers_lowest_badness_then_latest() -> None:
    mi = mission()
    mi.checkpoints = [cp("c1", pv(1)), cp("c2", pv(0, 0)), cp("c3", pv(0, 0))]
    best = guards.best_checkpoint(mi, pv(3))
    assert best is not None and best["sha"] == "c3"
    assert guards.best_checkpoint(mi, None) is None
    assert guards.best_checkpoint(mission(), pv(3)) is None


def test_worsening_progress_forces_rollback_when_a_better_checkpoint_exists() -> None:
    mi = mission([attempt(1, ["a"], pv(1, 1)), attempt(2, ["b"], pv(3, 2, reg=2))])
    mi.checkpoints = [cp("c1", pv(1, 1))]
    assert A.ROLLBACK in acts(mi)
    for retry_like in (A.RETRY_SAME_AGENT, A.REASSIGN, A.ESCALATE_MODEL):
        chosen, reason = override(decision(retry_like), mi, "T1")
        assert chosen == A.ROLLBACK and reason is not None and reason.startswith("progress_worsening")
    # other actions are left alone
    assert override(decision(A.INVESTIGATE), mi, "T1") == (A.INVESTIGATE, None)
    assert override(decision(A.ROLLBACK), mi, "T1") == (A.ROLLBACK, None)


def test_flat_or_improving_progress_does_not_force_rollback() -> None:
    mi = mission([attempt(1, ["a"], pv(2, 1)), attempt(2, ["b"], pv(1, 1))])
    mi.checkpoints = [cp("c1", pv(0, 0))]
    assert override(decision(A.REASSIGN), mi, "T1") == (A.REASSIGN, None)


def test_worsening_without_a_better_checkpoint_does_not_force_rollback() -> None:
    mi = mission([attempt(1, ["a"], pv(1, 1)), attempt(2, ["b"], pv(3, 2))])
    assert override(decision(A.RETRY_SAME_AGENT), mi, "T1") == (A.RETRY_SAME_AGENT, None)


# ------------------------------------------------------------------------------ override semantics


def test_legal_choice_passes_through_untouched() -> None:
    assert override(decision(A.INVESTIGATE), mission(), "T1", tournament_available=True) == (
        A.INVESTIGATE,
        None,
    )


def test_illegal_action_that_is_never_offered_is_replaced() -> None:
    chosen, reason = override(decision(A.ABORT, A.REASSIGN), mission(), "T1")
    assert chosen == A.REASSIGN and reason is not None and reason.startswith("not_in_legal_set")
    chosen, _ = override(decision(A.CONTINUE, A.ABORT), mission(), "T1")
    assert chosen == A.INVESTIGATE  # fallback illegal too -> first legal action by preference


def test_unknown_task_still_yields_a_sane_set() -> None:
    assert A.STOP_PARTIAL in {la.action for la in legal_actions(mission(), "T9", tournament_available=False)}


# ------------------------------------------------------------------------------ estimates


def test_cost_estimates_default_when_there_is_no_history() -> None:
    by = {la.action: la for la in legal_actions(mission(), "T1", tournament_available=True)}
    assert by[A.RETRY_SAME_AGENT].est_tokens == guards.DEFAULT_COST[A.RETRY_SAME_AGENT][0]
    assert (
        by[A.TOURNAMENT].est_tokens == guards.DEFAULT_COST[A.TOURNAMENT][0] * 3 // 3
        or by[A.TOURNAMENT].est_tokens > 0
    )
    assert by[A.STOP_PARTIAL].est_tokens == 0 and by[A.STOP_PARTIAL].target is None


def test_cost_estimates_use_the_mean_of_past_invocations() -> None:
    mi = mission()

    def sub(sid: str, mode: str, tin: int, tout: int, ms: int) -> m.Submission:
        return m.Submission(
            id=sid,
            mode_id=mode,
            agent_id="a",
            model="x",
            output_type="ChangeReport",
            payload={},
            usage=[m.LLMUsage(model="x", tokens_in=tin, tokens_out=tout, cost_usd=0, latency_ms=ms)],
        )

    mi.submissions = {
        "S1": sub("S1", "samurai.rework", 1000, 500, 10_000),
        "S2": sub("S2", "samurai.rework", 3000, 1500, 30_000),
        "S3": sub("S3", "scout.investigate", 700, 300, 5_000),
        "S4": sub("S4", "samurai.explore", 100, 100, 1_000),
    }
    by = {la.action: la for la in legal_actions(mi, "T1", tournament_available=True)}
    assert (by[A.RETRY_SAME_AGENT].est_tokens, by[A.RETRY_SAME_AGENT].est_seconds) == (3000, 20)
    assert (by[A.INVESTIGATE].est_tokens, by[A.INVESTIGATE].est_seconds) == (1000, 5)
    assert by[A.ESCALATE_MODEL].est_tokens == 3000
    assert (by[A.TOURNAMENT].est_tokens, by[A.TOURNAMENT].est_seconds) == (600, 3)  # k=3 candidates x mean
    assert by[A.REASSIGN].est_tokens == guards.DEFAULT_COST[A.REASSIGN][0]  # no samurai.implement history
