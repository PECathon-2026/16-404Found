"""build_stack assembles real components around injected fakes (no network, no G04/G05)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from orch_helpers import FakeHuman, FakeTestRunner, approve_all, green

from devpilot import wiring
from devpilot.config import Settings
from devpilot.core.events import EventType
from devpilot.llm import ScriptedLLM
from devpilot.state.event_store import read_events_sync
from devpilot.tools.gateway import DefaultToolGateway


async def make_stack(repo: Path, runs: Path, **kw: Any) -> wiring.MissionStack:
    params: dict[str, Any] = {
        "repo": repo,
        "request": "fix the pagination bug",
        "mode": "multi",
        "runs_dir": runs,
        "llm": ScriptedLLM([]),
        "human": FakeHuman(approve_all),
        "overrides": {"tests": FakeTestRunner([green])},
    }
    params.update(kw)
    return await wiring.build_stack(Settings(), **params)


async def test_stack_assembles(git_repo: Path, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    stack = await make_stack(git_repo, runs)
    try:
        assert stack.mission_id.startswith("M-") and len(stack.mission_id.split("-")) == 4
        assert len(stack.mission_id.rsplit("-", 1)[1]) == 4
        assert isinstance(stack.gateway, DefaultToolGateway)
        main = await stack.workspaces.path("main")
        assert main.is_dir() and (main / "pager" / "paginate.py").is_file()
        assert (await stack.workspaces.path("baseline")).is_dir()
        # MISSION_CREATED is on disk and the blackboard mirrors it
        events = read_events_sync(runs / stack.mission_id / "events.jsonl")
        assert events[0].type == EventType.MISSION_CREATED
        assert stack.blackboard.mission.workspace_path == str(main)
        assert stack.blackboard.mission.budget.limits == Settings().budgets
        # the human channel and orchestrator are wired to the same blackboard
        assert stack.orchestrator.bb.mission is stack.blackboard.mission
        assert stack.tests_available
    finally:
        await stack.shutdown()


async def test_missing_components_reports_tools_registry(git_repo: Path, tmp_path: Path) -> None:
    stack = await make_stack(git_repo, tmp_path / "runs")
    try:
        missing = wiring.missing_components(stack)
        assert "tool registry (WP-G04)" in missing
        assert not any(x.startswith("test runner") for x in missing)  # injected
        assert any("TOOL_UNAVAILABLE" in n for n in stack.notes)
    finally:
        await stack.shutdown()


async def test_tool_registry_override_is_called(git_repo: Path, tmp_path: Path) -> None:
    seen: list[wiring.ToolRegistryContext] = []

    def register_all(gateway: DefaultToolGateway, ctx: wiring.ToolRegistryContext) -> None:
        assert isinstance(gateway, DefaultToolGateway)
        seen.append(ctx)

    stack = await make_stack(
        git_repo,
        tmp_path / "runs",
        overrides={"tests": FakeTestRunner([green]), "tool_registry": register_all},
    )
    try:
        assert stack.tools_registered and len(seen) == 1
        assert seen[0].mission_id == stack.mission_id and seen[0].workspaces is stack.workspaces
        assert not any("tool registry" in x for x in wiring.missing_components(stack))
    finally:
        await stack.shutdown()


async def test_without_test_runner_stack_uses_placeholder(git_repo: Path, tmp_path: Path) -> None:
    stack = await make_stack(git_repo, tmp_path / "runs", overrides={})
    try:
        if wiring.probe_components()["test runner"]:
            pytest.skip("a real test runner (WP-G05) is installed")
        assert not stack.tests_available
        assert "test runner (WP-G05)" in wiring.missing_components(stack)
        with pytest.raises(wiring.ComponentUnavailableError):
            await stack.tests.run("full")
    finally:
        await stack.shutdown()


async def test_replay_mode_needs_no_api_key(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cassette = tmp_path / "c.jsonl"
    cassette.write_text("", encoding="utf-8")
    stack = await make_stack(git_repo, tmp_path / "runs", llm=None, cassette=cassette, cassette_mode="replay")
    try:
        assert stack.cassette_path == cassette
    finally:
        await stack.shutdown()


async def test_record_mode_without_key_is_a_clear_error(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(wiring.WiringError, match="ANTHROPIC_API_KEY"):
        await make_stack(git_repo, tmp_path / "runs", llm=None)


async def test_evidence_ids_are_mission_unique_across_workspaces(git_repo: Path, tmp_path: Path) -> None:
    from devpilot.core import models as m

    stack = await make_stack(git_repo, tmp_path / "runs")
    try:

        def evidence(ref: str) -> m.Evidence:
            return m.Evidence(
                id="E-0000",
                kind=m.EvidenceKind.TEST_RUN,
                tool="test.run",
                agent_id="a",
                workspace_ref=ref,
                workspace_sha="abc",
                summary="s",
                sha256="",
                log_path="",
            )

        a = await stack.ledger.record(evidence("main"), "one")
        b = await stack.ledger.record(evidence("baseline"), "two")
        assert (a.id, b.id) == ("E-0001", "E-0002")
        assert (a.workspace_ref, b.workspace_ref) == ("main", "baseline")
        assert stack.ledger.exists("E-0002") and Path(b.log_path).read_text(encoding="utf-8") == "two"
    finally:
        await stack.shutdown()
