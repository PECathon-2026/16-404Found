"""Behavioural tests of the Orchestrator with scripted modes: one test per distinctive behaviour."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from orch_helpers import (
    World,
    approve_review,
    assert_replay_matches,
    events_of,
    green,
    make_decision,
    make_plan,
    make_report,
    make_run,
    make_triage,
    make_world,
    pass_verdict,
    red,
    samurai,
)

from devpilot.config import Settings
from devpilot.core import models as m
from devpilot.core.events import Event, EventType
from devpilot.core.ports import ModeInvocation
from devpilot.engine.errors import ModeFailed, ModeRefused

PLAN_OK = [green, lambda n: make_run("acceptance", n=n, red=True), green]


def of(ev: list[Event], t: EventType, pred: Callable[[Event], bool] = lambda e: True) -> list[Event]:
    return [e for e in ev if e.type == t and pred(e)]


def happy(w: World) -> World:
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("samurai.rework", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    return w


# ------------------------------------------------------------------------------ planning


async def test_premortem_amendments_are_adopted_and_watches_installed(tmp_path: Path) -> None:
    w = happy(await make_world(tmp_path, plan=PLAN_OK))
    amended = make_plan(("T1", ["src/a.py"], []), ("T2", ["src/b.py"], ["T1"]))
    watch = m.WatchCondition(
        description="leap years", trigger="test_fails", pattern="*leap*", response=m.Action.INVESTIGATE
    )
    w.rt.queues["shogun.premortem"] = [
        m.PreMortem(risks=[], watch_conditions=[watch], plan_amendments=amended)
    ]

    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED

    mission = w.bb.mission
    assert len(mission.plans) == 1 and [t.key for t in mission.plans[0].plan.tasks] == ["T1", "T2"]
    assert mission.watch_conditions == [watch]
    assert all(t.plan_version == 1 for t in mission.tasks.values())
    ev = await events_of(w)
    ready = [
        e.payload["task_key"]
        for e in of(ev, EventType.TASK_STATE_CHANGED, lambda e: e.payload["to"] == "READY")
    ]
    assert ready[0] == "T1" and ready.count("T1") == 1  # only the dependency-free task starts READY


async def test_plan_gate_approve_and_cancel(tmp_path: Path) -> None:
    settings = Settings()
    settings.gates.plan = True
    w = happy(await make_world(tmp_path / "a", plan=PLAN_OK, settings=settings))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    states = [e.payload["to"] for e in of(await events_of(w), EventType.STATE_CHANGED)]
    assert states.index("AWAITING_PLAN_APPROVAL") < states.index("AUTHORING_ACCEPTANCE")

    settings2 = Settings()
    settings2.gates.plan = True
    w2 = happy(
        await make_world(tmp_path / "b", plan=PLAN_OK, settings=settings2, human=lambda p: ("cancel", None))
    )
    assert await w2.orch.run() == m.MissionStatus.ABORTED
    assert "sentinel.author_acceptance" not in w2.rt.modes()


async def test_plan_gate_edit_replans(tmp_path: Path) -> None:
    settings = Settings()
    settings.gates.plan = True
    answers = iter([(None, "split into two tasks"), ("approve", None), ("approve", None)])
    w = happy(await make_world(tmp_path, plan=PLAN_OK, settings=settings, human=lambda p: next(answers)))
    w.rt.queues["shogun.plan"] = [make_plan(), make_plan(("T1", ["src/a.py"], []), ("T2", ["src/b.py"], []))]
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    plans = [inv for inv in w.rt.calls if inv.mode_id == "shogun.plan"]
    assert plans[1].extra_context["human_feedback"] == "split into two tasks"
    assert len(w.bb.mission.plans) == 2


async def test_critical_mode_failure_fails_the_mission(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=PLAN_OK)
    w.rt.queues["scout.recon"] = [ModeFailed("scout.recon", "boom")]
    assert await w.orch.run() == m.MissionStatus.FAILED
    assert w.rt.modes().count("scout.recon") == 2  # retried once
    assert w.reports
    await assert_replay_matches(w)


# ------------------------------------------------------------------------------ scheduling


async def test_parallel_batches_respect_dependencies_and_file_locks(tmp_path: Path) -> None:
    barrier = asyncio.Barrier(2)

    w = await make_world(
        tmp_path, plan=[green, lambda n: make_run("acceptance", n=n, red=True), green, green, green]
    )
    w.rt.queues["shogun.plan"] = [
        make_plan(
            ("T1", ["a.py"], []), ("T2", ["b.py"], []), ("T3", ["a.py"], []), ("T4", ["c.py"], ["T1", "T2"])
        )
    ]

    async def concurrent(inv: ModeInvocation) -> m.ChangeReport:
        if inv.task_key in ("T1", "T2"):
            await asyncio.wait_for(barrier.wait(), 2)  # deadlocks unless T1 and T2 truly overlap
        w.ws.edit()
        return make_report()

    w.rt.script("samurai.implement", concurrent)
    w.rt.script("verifier.verify", pass_verdict())

    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    impl = [(i.task_key, i.agent_id) for i in w.rt.calls if i.mode_id == "samurai.implement"]
    # T3 shares a.py with T1 so it waits for the next wave; T4 waits for T1 and T2
    assert [k for k, _ in impl][:2] == ["T1", "T2"]
    assert {k for k, _ in impl} == {"T1", "T2", "T3", "T4"}
    assert [a for _, a in impl] == [f"samurai#{i}" for i in range(1, 5)]
    spawned = [e.payload["agent_id"] for e in of(await events_of(w), EventType.AGENT_SPAWNED)]
    assert spawned == [f"samurai#{i}" for i in range(1, 5)]
    # checkpoints after every batch
    assert w.ws.checkpoints >= 2


# ------------------------------------------------------------------------------ failure handling


async def test_mode_error_becomes_a_decision_point(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=PLAN_OK)
    w.rt.queues["samurai.implement"] = [ModeRefused("samurai.implement", "model refused"), samurai(w.ws)]
    w.rt.script("samurai.rework", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    w.rt.script("shogun.decide", make_decision(m.Action.REASSIGN))

    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)
    blocked = of(ev, EventType.TASK_STATE_CHANGED, lambda e: e.payload["to"] == "BLOCKED")
    assert blocked and "refused" in blocked[0].summary
    dec = of(ev, EventType.DECISION)[0]
    assert dec.payload["final_action"] == "REASSIGN"
    # REASSIGN spawns a fresh Samurai with samurai.implement
    impl = [i.agent_id for i in w.rt.calls if i.mode_id == "samurai.implement"]
    assert impl == ["samurai#1", "samurai#2"]
    assert w.bb.mission.tasks["T1"].attempts[0].outcome == "blocked"


async def test_blocked_change_report_goes_to_decide(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=PLAN_OK)
    w.rt.queues["samurai.implement"] = [make_report("blocked", blockers=["needs API key"])]
    w.rt.script("samurai.rework", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    decide = next(i for i in w.rt.calls if i.mode_id == "shogun.decide")
    assert "needs API key" in decide.extra_context["dossier"]["trigger_summary"]


async def test_triage_failure_falls_back_to_a_deterministic_finding(tmp_path: Path) -> None:
    w = happy(await make_world(tmp_path, plan=[*PLAN_OK[:2], red("zz"), green]))
    w.rt.queues["sentinel.triage"] = [ModeFailed("sentinel.triage", "x")]
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    fb = [f for f in w.bb.mission.findings.values() if f.source_mode == "orchestrator.fallback_triage"]
    assert fb and "test_ac2" in fb[0].summary
    inbox = next(box for inv, box in w.rt.inbox_at_call if inv.mode_id == "samurai.rework")
    assert any("test_ac2" in msg.body for msg in inbox)


async def test_preexisting_failures_are_not_a_red(tmp_path: Path) -> None:
    def run_with_preexisting(n: int) -> m.TestRun:
        r = make_run("full", n=n)
        old = r.cases[0].model_copy(
            update={
                "nodeid": "tests/test_legacy.py::test_old",
                "outcome": m.TestOutcome.FAILED,
                "classification": m.TestClass.STILL_FAILING,
                "is_acceptance": False,
            }
        )
        return r.model_copy(update={"verdict": "red", "cases": [*r.cases, old]})

    w = happy(await make_world(tmp_path, plan=[PLAN_OK[0], PLAN_OK[1], run_with_preexisting]))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    assert "sentinel.triage" not in w.rt.modes()


async def test_rollback_is_forced_when_progress_worsens(tmp_path: Path) -> None:
    w = await make_world(
        tmp_path,
        plan=[
            PLAN_OK[0],
            PLAN_OK[1],
            red("r1"),
            red("r2", regression=True, failing=("test_ac1", "test_ac2")),  # strictly worse
            green,
        ],
    )
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("samurai.rework", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    w.rt.script("sentinel.triage", make_triage("r1"), make_triage("r2"))
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))

    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)
    over = of(ev, EventType.GUARD_OVERRIDE)
    assert [o.payload["guard"] for o in over] == ["progress_worsening"]
    assert [d.payload["final_action"] for d in of(ev, EventType.DECISION)] == ["RETRY_SAME_AGENT", "ROLLBACK"]
    rb = of(ev, EventType.ROLLBACK)
    assert len(rb) == 1 and w.ws.rollbacks == [rb[0].payload["sha"]]
    best = [c for c in w.bb.mission.checkpoints if c["progress"]]
    assert best and rb[0].payload["sha"] == best[0]["sha"]
    assert of(ev, EventType.STRATEGY_CHANGED)[0].payload["to"] == "ROLLBACK"


async def test_replan_adopts_plan_v2_and_respects_max_replans(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=[PLAN_OK[0], PLAN_OK[1], red("p1"), green, green])
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    w.rt.queues["shogun.plan"] = [
        make_plan(),
        make_plan(("T1", ["src/pager.py"], []), ("T2", ["src/new.py"], [])),
    ]
    w.rt.script("sentinel.triage", make_triage("p1"))
    w.rt.script("shogun.decide", make_decision(m.Action.REPLAN))

    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    mission = w.bb.mission
    assert [p.version for p in mission.plans] == [1, 2]
    assert {t.plan_version for t in mission.tasks.values()} == {2}
    replan_inv = [i for i in w.rt.calls if i.mode_id == "shogun.plan"][1]
    assert replan_inv.extra_context["open_findings"] and "revised_because" in replan_inv.extra_context
    legal = [
        la["action"]
        for la in next(i for i in w.rt.calls if i.mode_id == "shogun.decide").extra_context["dossier"][
            "legal_actions"
        ]
    ]
    assert m.Action.REPLAN in legal


async def test_investigation_recommending_replan_replans(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=[PLAN_OK[0], PLAN_OK[1], red("i1"), green])
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    w.rt.queues["shogun.plan"] = [make_plan(), make_plan()]
    w.rt.script("sentinel.triage", make_triage("i1"))
    w.rt.script("shogun.decide", make_decision(m.Action.INVESTIGATE))
    w.rt.script(
        "scout.investigate",
        m.InvestigationReport(
            question="q",
            answer="needs another module",
            findings=[],
            locations=[],
            evidence_ids=[],
            recommends_replan=True,
            new_scope=["src/other.py"],
        ),
    )
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    inv = next(i for i in w.rt.calls if i.mode_id == "scout.investigate")
    assert inv.extra_context["question"]
    assert len(w.bb.mission.plans) == 2
    ev = await events_of(w)
    assert of(ev, EventType.FINDING, lambda e: e.payload["finding"]["kind"] == "investigation")


async def test_tournament_runs_the_injected_engine_and_is_otherwise_illegal(tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []
    holder: dict[str, World] = {}

    async def tournament(task_key: str, hints: list[str]) -> str:
        calls.append((task_key, hints))
        holder["w"].ws.edit()
        return "cand-B"

    w = await make_world(
        tmp_path / "a", plan=[PLAN_OK[0], PLAN_OK[1], red("t1"), green, green], tournament=tournament
    )
    holder["w"] = w
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    w.rt.script("sentinel.triage", make_triage("t1"))
    w.rt.script(
        "shogun.decide",
        make_decision(m.Action.TOURNAMENT, strategy_hints=["fix at call site", "fix in helper"]),
    )
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    assert calls == [("T1", ["fix at call site", "fix in helper"])]
    ev = await events_of(w)
    assert of(ev, EventType.TASK_STATE_CHANGED, lambda e: e.payload["to"] == "TOURNAMENT")
    assert w.bb.mission.tasks["T1"].attempts[-1].agent_id == "tournament:cand-B"

    # without an injected tournament engine TOURNAMENT is never offered and is overridden
    w2 = happy(await make_world(tmp_path / "b", plan=[PLAN_OK[0], PLAN_OK[1], red("t1"), green]))
    w2.rt.script("sentinel.triage", make_triage("t1"))
    w2.rt.script("shogun.decide", make_decision(m.Action.TOURNAMENT, fallback_if_fails=m.Action.REASSIGN))
    assert await w2.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    dossier = next(i for i in w2.rt.calls if i.mode_id == "shogun.decide").extra_context["dossier"]
    assert "TOURNAMENT" not in [la["action"] for la in dossier["legal_actions"]]
    over = of(await events_of(w2), EventType.GUARD_OVERRIDE)
    assert (
        over
        and over[0].payload["guard"] == "tournament_unavailable"
        and over[0].payload["final"] == "REASSIGN"
    )


# ------------------------------------------------------------------------------ checking


async def test_review_blocker_is_routed_and_blocks_apply(tmp_path: Path) -> None:
    state = {"n": 0}

    def reviewer(inv: ModeInvocation) -> m.ReviewReport:
        lens = m.ReviewLens(inv.extra_context["lens"])
        if lens == m.ReviewLens.CORRECTNESS and state["n"] == 0:
            state["n"] += 1
            f = m.ReviewFinding(
                severity="blocker",
                lens=lens,
                location="src/pager.py:L41",
                description="off by one",
                suggestion="use ceil",
                proven=True,
            )
            return m.ReviewReport(lens=lens, findings=[f], decision="request_changes")
        return approve_review(inv)

    w = await make_world(tmp_path, plan=[*PLAN_OK, green])
    w.rt.queues["reviewer.review"] = [reviewer]
    happy(w)
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)
    fs = of(
        ev,
        EventType.FINDING,
        lambda e: e.payload["finding"]["kind"] == "review" and e.payload["finding"]["status"] == "open",
    )
    assert len(fs) == 1 and fs[0].payload["finding"]["routed_to"] == "T1"
    prompts = of(ev, EventType.HUMAN_PROMPT)
    assert len(prompts) == 1  # the apply gate was only reached after the blocker was fixed


async def test_security_block_is_routed(tmp_path: Path) -> None:
    state = {"n": 0}

    def sec(inv: ModeInvocation) -> m.SecurityReport:
        if state["n"] == 0:
            state["n"] += 1
            f = m.SecurityFinding(
                severity="high",
                source="taint",
                introduced_by_change=True,
                location="src/pager.py:L9",
                description="sql injection",
                remediation="parameterise",
                cwe="CWE-89",
            )
            return m.SecurityReport(
                findings=[f], scanners_run=["taint"], scanners_unavailable=[], decision="block"
            )
        return m.SecurityReport(findings=[], scanners_run=["taint"], scanners_unavailable=[], decision="pass")

    w = await make_world(tmp_path, plan=[*PLAN_OK, green])
    w.rt.queues["security.inspect"] = [sec]
    happy(w)
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    f = next(f for f in w.bb.mission.findings.values() if f.kind == "security")
    assert f.severity == m.Severity.HIGH and f.routed_to == "T1" and "sql injection" in f.summary


async def test_stale_verdict_guard_reruns_checking(tmp_path: Path) -> None:
    state = {"n": 0}
    w = await make_world(tmp_path, plan=PLAN_OK)

    def verifier(_: ModeInvocation) -> m.VerifierVerdict:
        if state["n"] == 0:
            w.ws.edit()  # the tree moves while the verifier is running
        state["n"] += 1
        return pass_verdict()

    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", verifier)
    status = await w.orch.run()

    assert w.rt.modes().count("verifier.verify") == 2
    ev = await events_of(w)
    stale = of(ev, EventType.STATE_CHANGED, lambda e: "stale" in e.payload["reason"])
    assert len(stale) == 1 and stale[0].payload["from"] == "CHECKING" == stale[0].payload["to"]
    assert len(of(ev, EventType.VERDICT)) == 1  # the stale verdict was never recorded
    assert w.bb.mission.verdicts[0].diff_sha == await w.ws.tree_sha()
    # no passing test evidence exists for the new tree, so the ACs are not VERIFIED: honest partial
    assert status == m.MissionStatus.COMPLETED_PARTIAL
    assert all(a.status != m.ACStatus.VERIFIED for a in w.bb.mission.acs)


async def test_incomplete_checks_ask_a_human_instead_of_applying(tmp_path: Path) -> None:
    w = happy(await make_world(tmp_path, plan=PLAN_OK, human=lambda p: ("accept_partial", None)))
    w.rt.queues["verifier.verify"] = [ModeFailed("verifier.verify", "tool crashed")]
    w.rt.script("shogun.decide", make_decision(m.Action.ASK_HUMAN))
    status = await w.orch.run()
    assert status == m.MissionStatus.COMPLETED_PARTIAL
    assert w.rt.modes().count("verifier.verify") == 2  # one retry
    assert w.ws.applied == 0
    ev = await events_of(w)
    assert [p.payload["prompt"]["gate"] for p in of(ev, EventType.HUMAN_PROMPT)] == ["escalation"]


# ------------------------------------------------------------------------------ watch conditions


async def test_watch_condition_triggers_a_decision(tmp_path: Path) -> None:
    w = happy(await make_world(tmp_path, plan=[PLAN_OK[0], PLAN_OK[1], red("w1"), green]))
    watch = m.WatchCondition(
        description="acceptance 2 flaky",
        trigger="test_fails",
        pattern="*test_ac2",
        response=m.Action.INVESTIGATE,
    )
    w.rt.queues["shogun.premortem"] = [m.PreMortem(risks=[], watch_conditions=[watch])]
    w.rt.script("sentinel.triage", make_triage("w1"))
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)
    hits = of(ev, EventType.WATCH_TRIGGERED)
    assert len(hits) == 1 and hits[0].payload["suggested_response"] == "INVESTIGATE"
    decide = next(i for i in w.rt.calls if i.mode_id == "shogun.decide")
    assert decide.extra_context["watch_triggered"][0]["description"] == "acceptance 2 flaky"
    assert ev.index(hits[0]) < ev.index(of(ev, EventType.DECISION)[0])


async def test_budget_ratio_watch_fires_once(tmp_path: Path) -> None:
    w = happy(await make_world(tmp_path, plan=[PLAN_OK[0], PLAN_OK[1], green, green]))
    watch = m.WatchCondition(
        description="spent a lot", trigger="budget_ratio", pattern="0.0001", response=m.Action.STOP_PARTIAL
    )
    w.rt.queues["shogun.premortem"] = [m.PreMortem(risks=[], watch_conditions=[watch])]
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    await w.orch.run()
    assert len(of(await events_of(w), EventType.WATCH_TRIGGERED)) == 1


# ------------------------------------------------------------------------------ robustness


async def test_cancellation_aborts_and_still_reports(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=PLAN_OK)
    started = asyncio.Event()

    async def hang(_: ModeInvocation) -> m.ChangeReport:
        started.set()
        await asyncio.sleep(30)
        return make_report()

    w.rt.script("samurai.implement", hang)
    task = asyncio.create_task(w.orch.run())
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert w.bb.mission.status == m.MissionStatus.ABORTED
    assert w.reports, "the report is written even on cancellation"
    ev = await events_of(w)
    states = [e.payload["to"] for e in of(ev, EventType.STATE_CHANGED)]
    assert states[-2:] == ["REPORTING", "ABORTED"]
    assert ev[-1].type == EventType.MISSION_FINISHED
    await assert_replay_matches(w)


async def test_wall_clock_limit_ends_partial(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=PLAN_OK, limits=m.Budgets(max_wall_clock_s=1))

    async def slow(_: ModeInvocation) -> m.ChangeReport:
        await asyncio.sleep(30)
        return make_report()

    w.rt.script("samurai.implement", slow)
    status = await asyncio.wait_for(w.orch.run(), 10)
    assert status == m.MissionStatus.COMPLETED_PARTIAL
    ev = await events_of(w)
    assert of(ev, EventType.BUDGET_EXCEEDED)
    assert "wall clock" in (w.bb.mission.outcome_reason or "")
    assert w.reports


async def test_human_wait_does_not_count_against_the_wall_clock(tmp_path: Path) -> None:
    async def slow_human_run() -> m.MissionStatus:
        w = happy(await make_world(tmp_path, plan=PLAN_OK, limits=m.Budgets(max_wall_clock_s=1)))

        async def ask(prompt: m.HumanPrompt) -> m.HumanDecision:
            await asyncio.sleep(1.5)  # longer than the whole wall clock
            return m.HumanDecision(id="HD", prompt_id=prompt.id, choice="approve")

        w.orch.human = type("H", (), {"ask": staticmethod(ask)})()  # type: ignore[assignment]
        return await w.orch.run()

    assert await slow_human_run() == m.MissionStatus.COMPLETED_VERIFIED


async def test_reflection_and_report_failures_are_swallowed(tmp_path: Path) -> None:
    w = happy(await make_world(tmp_path, plan=PLAN_OK))
    w.rt.queues["shogun.reflect"] = [ModeFailed("shogun.reflect", "no")]

    async def bad_writer(_: m.Mission) -> None:
        raise OSError("disk full")

    w.orch.report_writer = bad_writer
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    assert not of(await events_of(w), EventType.REPORT_WRITTEN)

    w2 = happy(await make_world(tmp_path / "x", plan=PLAN_OK, reflect=False))
    assert await w2.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    assert "shogun.reflect" not in w2.rt.modes()


async def test_unexpected_exception_fails_the_mission_with_a_report(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=PLAN_OK)

    def explode(_: ModeInvocation) -> m.ChangeReport:
        raise KeyError("bug")

    w.rt.script("samurai.implement", explode)
    assert await w.orch.run() == m.MissionStatus.FAILED
    assert w.reports
    assert "KeyError" in (w.bb.mission.outcome_reason or "")


# ------------------------------------------------------------------------------ repo intelligence


class FakeIntelService:
    def __init__(self) -> None:
        self.tests_calls: list[tuple[str, tuple[int, ...]]] = []

    async def build(self, workspace: Path, request: str) -> m.RepoIntel:
        return m.RepoIntel(
            languages={"python": 1},
            file_count=1,
            test_framework="pytest",
            test_command=["pytest"],
            repo_map=[],
            conventions=[],
            risks=[],
        )

    async def rerank(self, query: str, k: int = 40) -> list[dict[str, Any]]:
        return []

    def callers_of(self, qualname: str) -> list[str]:
        return []

    def tests_covering(self, path: str, lines: Any) -> list[str]:
        self.tests_calls.append((path, tuple(lines)))
        return ["tests/test_acceptance.py::test_ac2"]


async def test_repo_intel_emits_intel_and_runs_targeted_before_full(tmp_path: Path) -> None:
    intel = FakeIntelService()
    w = happy(await make_world(tmp_path, plan=PLAN_OK, repo_intel=intel))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)
    assert ev.index(of(ev, EventType.INTEL_READY)[0]) < ev.index(of(ev, EventType.TEST_RUN)[0])
    assert w.bb.mission.intel is not None
    scopes = [c[0] for c in w.tests.calls]
    assert scopes == ["baseline", "acceptance", "targeted", "full"]
    assert w.tests.calls[2][1] == ("tests/test_acceptance.py::test_ac2",)
    assert intel.tests_calls == [("src/pager.py", ())]  # no hunks -> the task's files


async def test_red_targeted_run_skips_the_full_suite(tmp_path: Path) -> None:
    intel = FakeIntelService()
    w = happy(
        await make_world(
            tmp_path,
            plan=[
                PLAN_OK[0],
                PLAN_OK[1],
                lambda n: make_run("targeted", n=n, red=True, fp="tg1"),
                green,
                green,
            ],
            repo_intel=intel,
        )
    )
    w.rt.script("sentinel.triage", make_triage("tg1"))
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    assert [c[0] for c in w.tests.calls][:4] == ["baseline", "acceptance", "targeted", "targeted"]


async def test_intel_failure_is_not_fatal(tmp_path: Path) -> None:
    class Broken(FakeIntelService):
        async def build(self, workspace: Path, request: str) -> m.RepoIntel:
            raise RuntimeError("tree-sitter missing")

    w = happy(await make_world(tmp_path, plan=PLAN_OK, repo_intel=Broken()))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    assert of(await events_of(w), EventType.TOOL_UNAVAILABLE)


async def test_ddmin_runs_on_regressions_and_feeds_triage(tmp_path: Path) -> None:
    class DD:
        def __init__(self) -> None:
            self.seen: list[Any] = []

        async def isolate(self, failing_nodeids: Any) -> dict[str, Any]:
            self.seen.append(list(failing_nodeids))
            return {"culprit_hunks": ["h2"], "evidence_id": "E-0099"}

    dd = DD()
    w = happy(
        await make_world(
            tmp_path,
            plan=[PLAN_OK[0], PLAN_OK[1], red("dd1", regression=True), green, green],
            ddmin=dd,  # type: ignore[arg-type]
        )
    )
    w.rt.script("sentinel.triage", make_triage("dd1"))
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    assert dd.seen == [["tests/test_acceptance.py::test_ac2"]]
    triage = next(i for i in w.rt.calls if i.mode_id == "sentinel.triage")
    assert triage.extra_context["ddmin"]["culprit_hunks"] == ["h2"]
    assert of(await events_of(w), EventType.DELTA_DEBUG)


async def test_decide_failure_is_decided_deterministically_and_recorded(tmp_path: Path) -> None:
    w = happy(
        await make_world(
            tmp_path,
            plan=[PLAN_OK[0], PLAN_OK[1], red("d1"), green],
            human=lambda p: ("accept_partial", None),
        )
    )
    w.rt.script("sentinel.triage", make_triage("d1"))
    w.rt.queues["shogun.decide"] = [ModeFailed("shogun.decide", "repair rounds exhausted")]
    assert await w.orch.run() == m.MissionStatus.COMPLETED_PARTIAL
    ev = await events_of(w)
    dec = of(ev, EventType.DECISION)[0]
    assert dec.payload["final_action"] == "ASK_HUMAN"
    sub = w.bb.mission.decisions[0]
    assert sub.agent_id == "system" and "repair rounds exhausted" in sub.payload["justification"]


async def test_escalate_model_reworks_on_the_frontier_tier(tmp_path: Path) -> None:
    w = happy(await make_world(tmp_path, plan=[PLAN_OK[0], PLAN_OK[1], red("e1"), green]))
    w.rt.script("sentinel.triage", make_triage("e1"))
    w.rt.script("shogun.decide", make_decision(m.Action.ESCALATE_MODEL))
    assert await w.orch.run() == m.MissionStatus.COMPLETED_VERIFIED
    rework = next(i for i in w.rt.calls if i.mode_id == "samurai.rework")
    assert (
        rework.tier_override == m.ModelTier.FRONTIER
        and rework.attempt == 2
        and rework.agent_id == "samurai#1"
    )
    assert of(await events_of(w), EventType.MODEL_ESCALATED)
