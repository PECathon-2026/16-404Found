"""Run the orchestrator's FX2 scenario and expose its real event log (shared by report and memory tests)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("DEVPILOT_FSYNC", "0")  # faster JSONL store in tests (ignored if unsupported)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

from orch_helpers import (
    World,
    events_of,
    green,
    make_decision,
    make_report,
    make_run,
    make_triage,
    make_world,
    pass_verdict,
    red,
    reject_verdict,
    samurai,
)

from devpilot.core import models as m
from devpilot.core.events import Event


@dataclass
class Fx2:
    world: World
    events: list[Event]
    mission: m.Mission
    tree_sha: str


CHANGE_REPORT = make_report(
    claims=["Performance is unchanged"],
    files_changed=["src/pager.py"],
    approach="Use ceiling division for the page count",
)

FX2_DIFF = (
    "diff --git a/src/pager.py b/src/pager.py\n--- a/src/pager.py\n+++ b/src/pager.py\n"
    "@@ -1,2 +1,4 @@\n-pages = total // size\n+pages = -(-total // size)\n+assert pages >= 0\n+return pages\n"
)


async def run_fx2(tmp_path: Path, **kw: Any) -> Fx2:
    w = await make_world(
        tmp_path,
        plan=[
            green,
            lambda n: make_run("acceptance", n=n, red=True, fp="acc001"),
            red("a91f03"),
            green,
            green,
        ],
        **kw,
    )
    w.ws.diff_text = FX2_DIFF
    w.rt.script("samurai.implement", samurai(w.ws, CHANGE_REPORT))
    w.rt.script("samurai.rework", samurai(w.ws, CHANGE_REPORT))
    w.rt.script("sentinel.triage", make_triage("a91f03"))
    w.rt.script(
        "shogun.decide", make_decision(m.Action.RETRY_SAME_AGENT, strategy_hints=["use ceiling division"])
    )
    w.rt.script("verifier.verify", reject_verdict(), pass_verdict())
    status = await w.orch.run()
    assert status == m.MissionStatus.COMPLETED_VERIFIED
    return Fx2(w, await events_of(w), w.bb.mission, await w.ws.tree_sha())


__all__ = ["CHANGE_REPORT", "FX2_DIFF", "Fx2", "run_fx2"]
