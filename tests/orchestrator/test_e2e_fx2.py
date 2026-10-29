"""FX2 end to end: the demo's feedback loop (red -> triage -> retry -> verifier REJECT -> retry -> ACCEPT -> apply)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from orch_helpers import (
    FakeWorkspaces,
    assert_replay_matches,
    events_of,
    green,
    make_decision,
    make_run,
    make_triage,
    make_world,
    pass_verdict,
    red,
    reject_verdict,
    samurai,
)

from devpilot.core import models as m
from devpilot.core.events import Event, EventType


def find(
    events: list[Event], type_: EventType, start: int = 0, pred: Callable[[Event], bool] = lambda e: True
) -> int:
    """Index of the first event of ``type_`` at or after ``start`` that satisfies ``pred``."""
    for i in range(start, len(events)):
        if events[i].type == type_ and pred(events[i]):
            return i
    raise AssertionError(f"no {type_} (matching) after index {start}")


async def test_fx2_feedback_loop(tmp_path: Path) -> None:
    w = await make_world(
        tmp_path,
        plan=[
            green,  # 1 baseline
            lambda n: make_run("acceptance", n=n, red=True, fp="acc001"),  # 2 acceptance: red is expected
            red("a91f03"),  # 3 after attempt 1
            green,  # 4 after attempt 2
            green,  # 5 after attempt 3
        ],
    )
    ws: FakeWorkspaces = w.ws
    w.rt.script("samurai.implement", samurai(ws))
    w.rt.script("samurai.rework", samurai(ws))
    w.rt.script("sentinel.triage", make_triage("a91f03"))
    w.rt.script(
        "shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT, strategy_hints=["use ceiling division"])
    )
    w.rt.script("verifier.verify", reject_verdict(), pass_verdict())

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)

    # --- the feedback loop, in order -------------------------------------------------------
    i = find(
        ev,
        EventType.TEST_RUN,
        pred=lambda e: e.payload["test_run"]["verdict"] == "red" and e.payload["test_run"]["scope"] == "full",
    )
    i = find(ev, EventType.FINDING, i, lambda e: e.payload["finding"]["kind"] == "triage")
    i = find(
        ev,
        EventType.MESSAGE_SENT,
        i,
        lambda e: e.payload["message"]["to"] == "task:T1" and e.payload["message"]["sender"] == "sentinel",
    )
    i = find(ev, EventType.DECISION, i, lambda e: e.payload["final_action"] == "RETRY_SAME_AGENT")
    i = find(ev, EventType.TEST_RUN, i, lambda e: e.payload["test_run"]["verdict"] == "green")
    i = find(ev, EventType.VERDICT, i, lambda e: e.payload["verdict"]["verdict"]["overall"] == "REJECT")
    i = find(ev, EventType.FINDING, i, lambda e: e.payload["finding"]["kind"] == "verifier")
    assert "total=0" in ev[i].payload["finding"]["payload"]["counterexample"]
    i = find(ev, EventType.DECISION, i)
    i = find(ev, EventType.TEST_RUN, i, lambda e: e.payload["test_run"]["verdict"] == "green")
    i = find(ev, EventType.VERDICT, i, lambda e: e.payload["verdict"]["verdict"]["overall"] == "ACCEPT")
    # AC-1 was already verified on the first (rejected) tree; AC-2 failed there and verifies now.
    ac_events = [
        (e.payload["ac_id"], e.payload["status"]) for e in ev if e.type == EventType.AC_STATUS_CHANGED
    ]
    assert ac_events == [("AC-1", "VERIFIED"), ("AC-2", "FAILED"), ("AC-2", "VERIFIED")]
    i = find(
        ev,
        EventType.AC_STATUS_CHANGED,
        i,
        lambda e: e.payload["ac_id"] == "AC-2" and e.payload["status"] == "VERIFIED",
    )
    i = find(ev, EventType.HUMAN_PROMPT, i, lambda e: e.payload["prompt"]["gate"] == "apply")
    i = find(ev, EventType.HUMAN_DECISION, i)
    assert ev[i].actor == "human"
    i = find(ev, EventType.APPLIED, i)
    i = find(ev, EventType.MISSION_FINISHED, i)
    assert ev[i].payload["status"] == "COMPLETED_VERIFIED"
    assert ws.applied == 1

    # --- the retry saw the triage finding in its inbox ---------------------------------------
    reworks = [(inv, inbox) for inv, inbox in w.rt.inbox_at_call if inv.mode_id == "samurai.rework"]
    assert [inv.attempt for inv, _ in reworks] == [2, 3]
    assert {inv.agent_id for inv, _ in reworks} == {"samurai#1"}  # RETRY_SAME_AGENT keeps the agent
    first_inbox = reworks[0][1]
    triage_msgs = [msg for msg in first_inbox if msg.sender == "sentinel"]
    assert triage_msgs and "a91f03" in triage_msgs[0].body and "ceiling division" in triage_msgs[0].body
    assert reworks[0][0].extra_context["strategy_hint"] == "use ceiling division"
    # the verifier counterexample reached the third attempt
    third_inbox = reworks[1][1]
    assert any("total=0" in msg.body for msg in third_inbox if msg.sender == "verifier")

    # --- state machine hygiene ---------------------------------------------------------------
    phases = [e.payload["to"] for e in ev if e.type == EventType.STATE_CHANGED]
    assert phases[:6] == ["INTEL", "RECON", "ANALYZING", "PLANNING", "AUTHORING_ACCEPTANCE", "EXECUTING"]
    assert phases[-3:] == ["APPLYING", "REPORTING", "COMPLETED_VERIFIED"]
    assert all(e.payload.get("reason") for e in ev if e.type == EventType.STATE_CHANGED)
    # no guard fired and no strategy change on this path
    assert not [e for e in ev if e.type in (EventType.GUARD_OVERRIDE, EventType.STRATEGY_CHANGED)]
    # fix cycles are mirrored as events (2 fix cycles: one red, one verifier reject)
    assert [e.payload["fix_cycles"] for e in ev if e.type == EventType.BUDGET_WARNING] == [1, 2]
    # the baseline and the acceptance suite were run before any implementation
    assert [c[0] for c in w.tests.calls[:2]] == ["baseline", "acceptance"]
    assert w.rt.modes()[:7] == [
        "scout.recon",
        "shogun.analyze",
        "shogun.plan",
        "shogun.premortem",
        "sentinel.author_acceptance",
        "samurai.implement",
        "sentinel.triage",
    ]
    # checking ran verifier + 4 lenses + security in one go, twice
    assert w.rt.modes().count("reviewer.review") == 8
    lenses = {inv.extra_context["lens"] for inv in w.rt.calls if inv.mode_id == "reviewer.review"}
    assert lenses == {
        m.ReviewLens.CORRECTNESS,
        m.ReviewLens.CONSISTENCY,
        m.ReviewLens.TESTS,
        m.ReviewLens.REGRESSION,
    }

    # --- evidence-based completion -----------------------------------------------------------
    mission = w.bb.mission
    assert all(a.status == m.ACStatus.VERIFIED and a.confidence == 1.0 for a in mission.acs)
    assert mission.verdicts[-1].diff_sha == await ws.tree_sha()
    assert w.reports and w.reports[0].status == m.MissionStatus.REPORTING
    t1 = mission.tasks["T1"]
    assert t1.status == m.TaskStatus.DONE and [a.n for a in t1.attempts] == [1, 2, 3]
    assert t1.attempts[0].fingerprints == ["a91f03"] and t1.attempts[0].outcome == "red"
    await assert_replay_matches(w)
