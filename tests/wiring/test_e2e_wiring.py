"""Full wiring end to end: real store, blackboard, worktrees, gateway and bridge; scripted agents.

Only the LLM-facing AgentRuntime, the test runner and (for the answers-file test) nothing else are
fakes. The mission reaches a terminal state, the events file exists and replays to the live state.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from e2e_runtime import scripted_runtime
from orch_helpers import (
    FakeHuman,
    FakeTestRunner,
    approve_all,
    green,
    make_run,
)

from devpilot import wiring
from devpilot.config import Settings
from devpilot.core import models as m
from devpilot.core.events import EventType
from devpilot.core.ports import ToolContext
from devpilot.llm import ScriptedLLM
from devpilot.state.blackboard import EventSourcedBlackboard
from devpilot.state.event_store import JsonlEventStore, read_events_sync


async def build(repo: Path, runs: Path, settings: Settings | None = None, **kw: Any) -> wiring.MissionStack:
    params: dict[str, Any] = {
        "repo": repo,
        "request": "Last page of results is missing items",
        "mode": "multi",
        "runs_dir": runs,
        "llm": ScriptedLLM([]),
        "human": FakeHuman(approve_all),
        "overrides": {
            "runtime": scripted_runtime,
            "tests": FakeTestRunner([green, lambda n: make_run("acceptance", n=n, red=True), green]),
        },
    }
    params.update(kw)
    return await wiring.build_stack(settings or Settings(), **params)


async def test_mission_runs_to_verified_through_real_wiring(git_repo: Path, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    settings = Settings()
    settings.chaos.disable_tools = ["fs.read"]  # wired into the gateway; it announces TOOL_UNAVAILABLE
    stack = await build(git_repo, runs, settings)
    try:
        # A gateway call on a disabled tool: the bridge must carry its event to the real log.
        ctx = ToolContext(
            mission_id=stack.mission_id,
            agent_id="samurai#1",
            mode_id="samurai.implement",
            task_key="T1",
            workspace_ref="main",
            allowed_tools=frozenset({"fs.read"}),
        )
        res = await stack.gateway.execute(ctx, "fs_read", {"path": "pager/paginate.py", "rationale": "look"})
        assert not res.ok and res.error_code == "TOOL_UNAVAILABLE"

        status = await stack.orchestrator.run()
        await stack.bridge.drain()

        assert status.terminal
        assert status == m.MissionStatus.COMPLETED_VERIFIED, stack.blackboard.mission.outcome_reason
        events_file = runs / stack.mission_id / "events.jsonl"
        assert events_file.is_file()
        events = read_events_sync(events_file)
        types = [e.type for e in events]
        assert types[0] == EventType.MISSION_CREATED and EventType.MISSION_FINISHED in types
        assert stack.bridge.delivered >= 1 and stack.bridge.failed == 0
        assert EventType.TOOL_UNAVAILABLE in types  # delivered by the bridge, in the real log
        assert EventType.HUMAN_PROMPT in types and EventType.APPLIED in types

        # report artefacts and memory
        out = runs / stack.mission_id
        for name in ("REPORT.md", "report.html", "mission.json"):
            assert (out / name).is_file(), name
        assert "Verified" in (out / "REPORT.md").read_text(encoding="utf-8")
        assert not (out / "REPORT_REFUSED.txt").exists()
        written = [e for e in events if e.type == EventType.REPORT_WRITTEN]
        assert any(str(out / "REPORT.md") == e.payload.get("path") for e in written)
        mem_events = [e for e in events if e.type == EventType.MEMORY_WRITTEN]
        assert len(mem_events) == 1
        stored = await stack.memory._inner.list_items()  # type: ignore[union-attr,attr-defined]
        assert len(stored) >= 1 and mem_events[0].payload["count"] >= len(stored)
        assert sum(mem_events[0].payload["kinds"].values()) == mem_events[0].payload["count"]
        assert (tmp_path / "memory.sqlite").is_file()

        # the change really landed in the target repository
        assert "fixed by the scripted samurai" in (git_repo / "pager" / "paginate.py").read_text(
            encoding="utf-8"
        )

        # event sourcing integrity through the real store
        loaded = await EventSourcedBlackboard.load(JsonlEventStore(runs), stack.mission_id)
        assert loaded.mission.model_dump(mode="json") == stack.blackboard.mission.model_dump(mode="json")
    finally:
        await stack.shutdown()


async def test_answers_file_rejects_apply_and_nothing_is_applied(git_repo: Path, tmp_path: Path) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text('{"apply": "reject"}', encoding="utf-8")
    original = (git_repo / "pager" / "paginate.py").read_text(encoding="utf-8")
    stack = await build(git_repo, tmp_path / "runs", human=None, answers=answers)
    try:
        status = await stack.orchestrator.run()
        assert status == m.MissionStatus.COMPLETED_PARTIAL
        assert (git_repo / "pager" / "paginate.py").read_text(encoding="utf-8") == original
        decisions = stack.blackboard.mission.human_decisions
        assert decisions and decisions[-1].source == "answers_file" and decisions[-1].choice == "reject"
    finally:
        await stack.shutdown()


async def test_reloaded_orchestrator_keeps_budget_counters(git_repo: Path, tmp_path: Path) -> None:
    """BUDGET_WARNING carries the counters, so a reload from events.jsonl starts from them."""
    runs = tmp_path / "runs"
    stack = await build(git_repo, runs)
    try:
        await stack.blackboard.emit(
            EventType.BUDGET_WARNING,
            "system",
            {"fix_cycles": 3, "tournaments": 1, "wall_clock_s": 42.5},
        )
        reloaded = await EventSourcedBlackboard.load(JsonlEventStore(runs), stack.mission_id)
        b = reloaded.mission.budget
        assert (b.fix_cycles, b.tournaments, b.wall_clock_s) == (3, 1, 42.5)
        from orch_helpers import ScriptedRuntime as SR

        from devpilot.orchestrator.orchestrator import Orchestrator

        orch = Orchestrator(
            reloaded,  # type: ignore[arg-type]
            SR(reloaded),
            stack.workspaces,
            stack.tests,
            stack.human,
            Settings(),
        )
        # run() returns immediately for terminal missions, so seed through a short run instead
        reloaded.mission.status = m.MissionStatus.COMPLETED_PARTIAL
        await orch.run()
        assert reloaded.mission.budget.fix_cycles == 3
        # a fresh (non-terminal) run re-seeds its private counters from the mission
        reloaded.mission.status = m.MissionStatus.CREATED
        orch2 = Orchestrator(reloaded, SR(reloaded), stack.workspaces, stack.tests, stack.human, Settings())  # type: ignore[arg-type]
        with contextlib.suppress(Exception):  # the unscripted runtime fails; we only inspect counters
            await orch2.run()
        assert orch2._fix_cycles == 3 and orch2._tournaments == 1
    finally:
        await stack.shutdown()


async def test_devpilot_report_rerenders_from_events(git_repo: Path, tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from devpilot.cli import app

    runs = tmp_path / "runs"
    stack = await build(git_repo, runs)
    try:
        await stack.orchestrator.run()
    finally:
        await stack.shutdown()
    (runs / stack.mission_id / "REPORT.md").unlink()
    runner = CliRunner()
    # CliRunner starts its own event loop via asyncio.run, so run it off this loop's thread
    result = await asyncio.to_thread(
        runner.invoke, app, ["report", stack.mission_id, "--runs-dir", str(runs)]
    )
    assert result.exit_code == 0, result.output
    assert "Verified" in result.output
    assert (runs / stack.mission_id / "REPORT.md").is_file()
    html = await asyncio.to_thread(
        runner.invoke, app, ["report", stack.mission_id, "--runs-dir", str(runs), "--html"]
    )
    assert html.exit_code == 0 and "report.html" in html.output
    missing = await asyncio.to_thread(runner.invoke, app, ["report", "M-nope", "--runs-dir", str(runs)])
    assert missing.exit_code == 66
