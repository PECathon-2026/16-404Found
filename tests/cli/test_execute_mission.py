"""execute_mission: the live view, human gates in the loop and clean Ctrl-C cancellation."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from orch_helpers import FakeHuman, FakeTestRunner, approve_all, green
from rich.console import Console

from devpilot import wiring
from devpilot.cli import _print_summary, execute_mission
from devpilot.cli_view import MissionView, agent_colour, phase_stepper
from devpilot.config import Settings
from devpilot.core import models as m
from devpilot.core.events import Event, EventType
from devpilot.llm import ScriptedLLM
from devpilot.state.event_store import read_events_sync


class HangingRuntime:
    """An AgentRuntime that never returns (a long LLM call)."""

    async def invoke(self, inv: Any) -> Any:
        await asyncio.sleep(3600)


async def build(repo: Path, runs: Path, runtime: Any) -> wiring.MissionStack:
    return await wiring.build_stack(
        Settings(),
        repo=repo,
        request="fix pagination",
        mode="multi",
        runs_dir=runs,
        llm=ScriptedLLM([]),
        human=FakeHuman(approve_all),
        overrides={"runtime": runtime, "tests": FakeTestRunner([green])},
    )


def console_to(buf: io.StringIO) -> Console:
    return Console(file=buf, width=120, force_terminal=False, legacy_windows=False)


async def test_cancel_aborts_mission_and_reports(git_repo: Path, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    stack = await build(git_repo, runs, HangingRuntime())
    buf = io.StringIO()
    try:
        task = asyncio.create_task(execute_mission(stack, console_to(buf), quiet=False))
        await asyncio.sleep(0.5)  # the orchestrator is now inside the first (hanging) mode
        task.cancel()
        status, cancelled = await task
    finally:
        await stack.shutdown()
    assert cancelled and status == m.MissionStatus.ABORTED
    events = read_events_sync(runs / stack.mission_id / "events.jsonl")
    assert events[-1].type == EventType.MISSION_FINISHED
    assert events[-1].payload["status"] == "ABORTED"
    out = buf.getvalue()
    assert stack.mission_id in out and "ABORTED" in out
    rdir = runs / stack.mission_id
    assert (rdir / "REPORT.md").is_file() and (rdir / "report.html").is_file()  # aborted still reports
    summary = io.StringIO()
    _print_summary(console_to(summary), stack, status)
    assert "REPORT.md:" in summary.getvalue()
    assert "report.html" in summary.getvalue()


async def test_live_view_renders_header_budget_timeline(git_repo: Path, tmp_path: Path) -> None:
    from e2e_runtime import scripted_runtime  # tests/wiring helper

    stack = await build(git_repo, tmp_path / "runs", scripted_runtime)
    buf = io.StringIO()
    try:
        status, cancelled = await execute_mission(stack, console_to(buf), quiet=False)
    finally:
        await stack.shutdown()
    assert status == m.MissionStatus.COMPLETED_VERIFIED and not cancelled
    out = buf.getvalue()
    for needle in ("COMPLETED_VERIFIED", "tokens", "fix cycles", "timeline", "plan", "T1", "samurai"):
        assert needle in out, needle


async def test_quiet_mode_prints_no_live_view(git_repo: Path, tmp_path: Path) -> None:
    stack = await build(git_repo, tmp_path / "runs", HangingRuntime())
    buf = io.StringIO()
    try:
        task = asyncio.create_task(execute_mission(stack, console_to(buf), quiet=True))
        await asyncio.sleep(0.3)
        task.cancel()
        await task
    finally:
        await stack.shutdown()
    assert buf.getvalue() == ""


def test_stepper_and_colours() -> None:
    text = phase_stepper(m.MissionStatus.EXECUTING).plain
    assert "[x] INTEL" in text and "[>] EXECUTING" in text and "[ ] CHECKING" in text
    assert "[>]" not in phase_stepper(m.MissionStatus.COMPLETED_VERIFIED).plain
    assert agent_colour("samurai#2") == "#D4A84B" and agent_colour("system") == "#8A8F98"


def test_view_keeps_last_15_lines_and_active_modes() -> None:
    mission = m.Mission(id="M-x", request="r", repo_path="/r", workspace_path="/w")
    view = MissionView(mission, model_for=lambda mode: "claude-x")
    for i in range(1, 31):
        view.feed(Event(seq=i, mission_id="M-x", type=EventType.TOOL_CALL, actor="scout", summary=f"s{i}"))
    view.feed(
        Event(seq=31, mission_id="M-x", type=EventType.AGENT_TEXT_DELTA, actor="scout", summary="delta")
    )
    assert next(e.summary for e in view.timeline) == "s16" and len(view.timeline) == 15
    view.feed(
        Event(seq=32, mission_id="M-x", type=EventType.MODE_STARTED, actor="shogun", mode_id="shogun.plan")
    )
    assert view.active == {"shogun": ("shogun.plan", "claude-x")}
    view.feed(
        Event(seq=33, mission_id="M-x", type=EventType.MODE_FINISHED, actor="shogun", mode_id="shogun.plan")
    )
    assert view.active == {}
