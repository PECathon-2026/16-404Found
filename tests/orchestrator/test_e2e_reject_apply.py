"""The apply gate is mandatory and rejecting it applies nothing."""

from __future__ import annotations

from pathlib import Path

from orch_helpers import (
    assert_replay_matches,
    events_of,
    green,
    make_decision,
    make_run,
    make_world,
    pass_verdict,
    samurai,
)

from devpilot.core import models as m
from devpilot.core.events import EventType


def _plan() -> list:  # type: ignore[type-arg]
    return [green, lambda n: make_run("acceptance", n=n, red=True), green]


async def test_reject_at_apply_gate(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=_plan(), human=lambda p: ("reject", "not now"))
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_PARTIAL
    assert w.ws.applied == 0  # apply_to_target is never called
    ev = await events_of(w)
    assert not [e for e in ev if e.type == EventType.APPLIED]
    prompts = [e.payload["prompt"] for e in ev if e.type == EventType.HUMAN_PROMPT]
    assert [p["gate"] for p in prompts] == ["apply"]
    body = prompts[0]["body_md"]
    assert (
        "AC-1" in body and "VERIFIED" in body and "Tests" in body and "Security" in body and "Review" in body
    )
    states = [e.payload["to"] for e in ev if e.type == EventType.STATE_CHANGED]
    assert states[-4:] == ["CHECKING", "AWAITING_APPLY", "REPORTING", "COMPLETED_PARTIAL"]
    assert "APPLYING" not in states
    assert w.bb.mission.outcome_reason == "human rejected the change at the apply gate"
    await assert_replay_matches(w)


async def test_request_changes_routes_to_shogun_then_decides(tmp_path: Path) -> None:
    answers = iter([("request_changes", "please also handle page size 0"), ("approve", None)])
    w = await make_world(tmp_path, plan=[*_plan(), green], human=lambda p: next(answers))
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("samurai.rework", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)
    msgs = [e.payload["message"] for e in ev if e.type == EventType.MESSAGE_SENT]
    to_shogun = [x for x in msgs if x["to"] == "shogun"]
    assert to_shogun and "page size 0" in to_shogun[0]["body"]
    decide_inv = next(inv for inv in w.rt.calls if inv.mode_id == "shogun.decide")
    assert decide_inv.extra_context["dossier"]["trigger_summary"].startswith("human requested changes")
    assert decide_inv.extra_context["human_feedback"] == "please also handle page size 0"
    # the request reaches the Samurai through the task inbox
    rework_inbox = next(box for inv, box in w.rt.inbox_at_call if inv.mode_id == "samurai.rework")
    assert any("page size 0" in msg.body for msg in rework_inbox)
    assert [p.payload["prompt"]["gate"] for p in ev if p.type == EventType.HUMAN_PROMPT] == ["apply", "apply"]
    assert w.ws.applied == 1
    await assert_replay_matches(w)


async def test_unclear_answer_never_applies(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=_plan(), human=lambda p: (None, None))
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_PARTIAL
    assert w.ws.applied == 0


async def test_apply_failure_is_partial(tmp_path: Path) -> None:
    w = await make_world(tmp_path, plan=_plan())
    w.ws.apply_error = RuntimeError("target repo is dirty")
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_PARTIAL
    ev = await events_of(w)
    assert not [e for e in ev if e.type == EventType.APPLIED]
    assert "dirty" in (w.bb.mission.outcome_reason or "")
    await assert_replay_matches(w)
