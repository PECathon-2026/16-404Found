"""High ambiguity raises a clarification gate and re-analyses with the human's answer."""

from __future__ import annotations

from pathlib import Path

from orch_helpers import (
    assert_replay_matches,
    events_of,
    green,
    make_run,
    make_spec,
    make_world,
    pass_verdict,
    samurai,
)

from devpilot.core import models as m
from devpilot.core.events import EventType


def high_ambiguity_spec() -> m.MissionSpec:
    return make_spec(
        m.Ambiguity(
            level=m.Level.HIGH,
            question="Should empty pages be shown?",
            options=[
                m.ClarifyingOption(key="show", label="Show empty pages", consequence="UI keeps blank pages"),
                m.ClarifyingOption(key="hide", label="Hide empty pages", consequence="pages are compacted"),
            ],
            default_option="hide",
        )
    )


async def test_clarification_then_reanalysis_with_answer(tmp_path: Path) -> None:
    def human(prompt: m.HumanPrompt) -> tuple[str | None, str | None]:
        return (
            ("hide", "and keep page numbers stable") if prompt.gate == "clarification" else ("approve", None)
        )

    w = await make_world(
        tmp_path,
        plan=[green, lambda n: make_run("acceptance", n=n, red=True), green],
        human=human,
    )
    w.rt.queues["shogun.analyze"] = [high_ambiguity_spec(), make_spec()]
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("verifier.verify", pass_verdict())

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_VERIFIED
    ev = await events_of(w)
    states = [e.payload["to"] for e in ev if e.type == EventType.STATE_CHANGED]
    assert states[:5] == ["INTEL", "RECON", "ANALYZING", "CLARIFYING", "ANALYZING"]
    prompt_i = next(i for i, e in enumerate(ev) if e.type == EventType.HUMAN_PROMPT)
    prompt = ev[prompt_i].payload["prompt"]
    assert prompt["gate"] == "clarification"
    assert [o["key"] for o in prompt["options"]] == ["show", "hide"]  # options come from the spec
    decision_i = next(i for i, e in enumerate(ev) if e.type == EventType.HUMAN_DECISION)
    assert decision_i > prompt_i and ev[decision_i].actor == "human"

    analyses = [inv for inv in w.rt.calls if inv.mode_id == "shogun.analyze"]
    assert len(analyses) == 2
    assert "clarification" not in analyses[0].extra_context
    clar = analyses[1].extra_context["clarification"]
    assert "Hide empty pages" in clar and "page numbers stable" in clar
    # the second analysis is what the mission continued with
    assert w.bb.mission.spec is not None and w.bb.mission.spec.ambiguity.level == m.Level.LOW
    await assert_replay_matches(w)


async def test_cancel_at_clarification_aborts(tmp_path: Path) -> None:
    w = await make_world(
        tmp_path,
        plan=[green],
        human=lambda p: ("cancel", None),
    )
    w.rt.queues["shogun.analyze"] = [high_ambiguity_spec()]

    status = await w.orch.run()

    assert status == m.MissionStatus.ABORTED
    ev = await events_of(w)
    states = [e.payload["to"] for e in ev if e.type == EventType.STATE_CHANGED]
    assert states[-2:] == ["REPORTING", "ABORTED"]  # an aborted mission still produces a report
    assert w.reports
    assert "shogun.plan" not in w.rt.modes() and "shogun.reflect" not in w.rt.modes()
    assert ev[-1].type == EventType.MISSION_FINISHED and ev[-1].payload["status"] == "ABORTED"
    await assert_replay_matches(w)
