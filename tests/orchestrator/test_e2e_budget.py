"""A tiny fix-cycle budget ends the mission partial instead of looping."""

from __future__ import annotations

from pathlib import Path

from orch_helpers import (
    assert_replay_matches,
    events_of,
    green,
    make_decision,
    make_run,
    make_triage,
    make_world,
    samurai,
)

from devpilot.core import models as m
from devpilot.core.events import EventType


async def test_max_fix_cycles_stops_partial(tmp_path: Path) -> None:
    w = await make_world(
        tmp_path,
        plan=[
            green,
            lambda n: make_run("acceptance", n=n, red=True),
            lambda n: make_run("full", n=n, red=True, fp=f"fp{n}"),
        ],
        limits=m.Budgets(max_fix_cycles=1),
    )
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("samurai.rework", samurai(w.ws))
    w.rt.script("sentinel.triage", make_triage("fpX"))
    w.rt.script("shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT))

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_PARTIAL
    ev = await events_of(w)
    decisions = [e for e in ev if e.type == EventType.DECISION]
    assert [d.payload["final_action"] for d in decisions] == ["RETRY_SAME_AGENT", "STOP_PARTIAL"]
    # one fix cycle was allowed, then the only legal action was STOP_PARTIAL: no LLM call needed
    assert w.rt.modes().count("shogun.decide") == 1
    assert decisions[1].payload["overridden_by_guard"] is None
    assert [e.payload["fix_cycles"] for e in ev if e.type == EventType.BUDGET_WARNING] == [1]
    stop_sub = w.bb.mission.decisions[-1]
    assert stop_sub.agent_id == "system" and stop_sub.model == "deterministic"
    assert w.bb.mission.outcome_reason is not None and "legal" in w.bb.mission.outcome_reason
    assert w.reports, "a report is produced even when the mission stops early"
    await assert_replay_matches(w)


async def test_exhausted_token_budget_stops_partial_without_llm_decision(tmp_path: Path) -> None:
    """Once the budget ratio is >= 1 the only legal action is STOP_PARTIAL."""
    w = await make_world(
        tmp_path,
        plan=[
            green,
            lambda n: make_run("acceptance", n=n, red=True),
            lambda n: make_run("full", n=n, red=True, fp="t1"),
        ],
        limits=m.Budgets(
            max_tokens_mission=1000
        ),  # 150 tokens per scripted call: spent after the triage call
    )
    w.rt.script("samurai.implement", samurai(w.ws))
    w.rt.script("sentinel.triage", make_triage("t1"))

    status = await w.orch.run()

    assert status == m.MissionStatus.COMPLETED_PARTIAL
    assert w.rt.modes().count("shogun.decide") == 0
    await assert_replay_matches(w)
