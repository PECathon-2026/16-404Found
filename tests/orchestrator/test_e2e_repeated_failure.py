"""Bounded autonomy end to end: the same failure fingerprint recurs and the guards take over."""

from __future__ import annotations

from pathlib import Path

from orch_helpers import (
    assert_replay_matches,
    events_of,
    green,
    make_decision,
    make_report,
    make_run,
    make_triage,
    make_world,
    samurai,
)

from devpilot.core import models as m
from devpilot.core.events import EventType
from devpilot.orchestrator.orchestrator import MAX_PHASES


def make_investigation() -> m.InvestigationReport:
    return m.InvestigationReport(
        question="why?",
        answer="the helper rounds down",
        findings=["pager.paginate floors"],
        locations=["src/pager.py:L41"],
        evidence_ids=[],
        recommends_replan=False,
    )


async def test_same_fingerprint_three_times_asks_human_then_partial(tmp_path: Path) -> None:
    seen_gates: list[str] = []

    def human(prompt: m.HumanPrompt) -> tuple[str | None, str | None]:
        seen_gates.append(prompt.gate)
        return "accept_partial", None

    w = await make_world(
        tmp_path,
        plan=[
            green,
            lambda n: make_run("acceptance", n=n, red=True),
            lambda n: make_run("full", n=n, red=True, fp="same001"),
        ],
        human=human,
    )
    w.rt.script("samurai.implement", samurai(w.ws, make_report()))
    w.rt.script("samurai.rework", samurai(w.ws, make_report()))
    w.rt.script("sentinel.triage", make_triage("same001"))
    w.rt.script("scout.investigate", make_investigation())
    # the Shogun keeps asking for the same thing; the guards must not follow it forever
    w.rt.script(
        "shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT, fallback_if_fails=m.Action.INVESTIGATE)
    )

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_PARTIAL
    ev = await events_of(w)
    decisions = [e for e in ev if e.type == EventType.DECISION]
    assert [d.payload["final_action"] for d in decisions] == ["RETRY_SAME_AGENT", "INVESTIGATE", "ASK_HUMAN"]
    assert [d.payload["proposed_action"] for d in decisions] == ["RETRY_SAME_AGENT"] * 3

    # 2nd occurrence: RETRY forbidden -> STRATEGY_CHANGED + GUARD_OVERRIDE
    overrides = [e for e in ev if e.type == EventType.GUARD_OVERRIDE]
    assert [o.payload["guard"] for o in overrides] == ["repeat_fingerprint_2", "repeat_fingerprint_3"]
    strategy = [e for e in ev if e.type == EventType.STRATEGY_CHANGED]
    assert strategy and strategy[0].payload["to"] == "INVESTIGATE"
    assert (
        ev.index(strategy[0]) < ev.index(decisions[2]) and ev.index(strategy[0]) > ev.index(decisions[1]) - 3
    )
    # 3rd occurrence: the human is asked, they accept partial
    prompt_i = next(
        i
        for i, e in enumerate(ev)
        if e.type == EventType.HUMAN_PROMPT and e.payload["prompt"]["gate"] == "escalation"
    )
    assert prompt_i > ev.index(decisions[2])
    assert seen_gates == ["escalation"]
    assert [o["key"] for o in w.human.prompts[0].model_dump()["options"]] == [
        "guidance",
        "accept_partial",
        "abort",
    ]

    # bounded: three samurai attempts, one investigation, three decisions, no infinite loop
    modes = w.rt.modes()
    assert modes.count("samurai.implement") + modes.count("samurai.rework") == 3
    assert modes.count("scout.investigate") == 1
    assert modes.count("shogun.decide") == 3
    assert len(modes) < 25
    assert len(ev) < MAX_PHASES * 5

    mission = w.bb.mission
    assert mission.outcome_reason == "human accepted a partial result"
    assert not [e for e in ev if e.type == EventType.APPLIED]
    assert w.ws.applied == 0
    assert mission.tasks["T1"].attempts[-1].fingerprints == ["same001"]
    await assert_replay_matches(w)


async def test_human_guidance_reworks_the_task(tmp_path: Path) -> None:
    """ASK_HUMAN -> 'guidance' puts the human's text in the task inbox and reworks."""
    answers = iter([("guidance", "look at the floor division in paginate"), ("accept_partial", None)])

    def human(prompt: m.HumanPrompt) -> tuple[str | None, str | None]:
        return next(answers)

    w = await make_world(
        tmp_path,
        plan=[
            green,
            lambda n: make_run("acceptance", n=n, red=True),
            lambda n: make_run("full", n=n, red=True, fp="g1"),
        ],
        human=human,
    )
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("samurai.rework", samurai(w.ws))
    w.rt.script("sentinel.triage", make_triage("g1"))
    w.rt.script("shogun.decide", make_decision(m.Action.ASK_HUMAN, question_for_human="what now?"))

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_PARTIAL
    reworks = [(inv, inbox) for inv, inbox in w.rt.inbox_at_call if inv.mode_id == "samurai.rework"]
    assert reworks, "guidance must lead to a rework"
    assert any("floor division" in msg.body for msg in reworks[0][1] if msg.sender == "human")
    await assert_replay_matches(w)
