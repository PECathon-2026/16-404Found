"""Unit tests for DevPilot tool implementations and registry (WP-G04)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from devpilot.config import load_settings
from devpilot.core.ports import ToolContext, Workspaces
from devpilot.tools.executor_local import LocalExecutor
from devpilot.tools.gateway import DefaultToolGateway
from devpilot.tools.ledger import FileEvidenceLedger
from devpilot.tools.registry import (
    FsEditTool,
    FsListTool,
    FsReadTool,
    FsWriteProbeTool,
    FsWriteTool,
    SearchCodeTool,
    ShellRunTool,
    register_all,
)
from devpilot.wiring import ToolRegistryContext


class SimpleWorkspaces(Workspaces):
    """Minimal test workspace for unit testing tools."""

    def __init__(self, root: Path) -> None:
        self.root = root

    async def create_main(self, target: Path, mission_id: str) -> Path:
        return self.root

    async def create_baseline(self) -> Path:
        return self.root

    async def path(self, ref: str = "main") -> Path:
        return self.root

    async def tree_sha(self, ref: str = "main") -> str:
        return "0" * 40

    async def fork(self, new_ref: str, from_ref: str = "main") -> Path:
        return self.root

    async def diff(self, against: str = "baseline", ref: str = "main") -> str:
        return ""

    async def hunks(self, ref: str = "main") -> list[dict[str, object]]:  # type: ignore[override]
        return []

    async def checkpoint(self, message: str, ref: str = "main") -> str:
        return "sha"

    async def rollback(self, to_checkpoint: str, ref: str = "main") -> None:
        pass

    async def adopt(self, candidate: str) -> None:
        pass

    async def apply_to_target(self) -> str:
        return "sha"


@pytest.fixture
def test_env(tmp_path: Path) -> tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext]:
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    ws = SimpleWorkspaces(ws_dir)
    executor = LocalExecutor()
    ctx = ToolContext(
        mission_id="M-TEST-001",
        agent_id="test_agent",
        mode_id="samurai.implement",
        task_key="T1",
        workspace_ref="main",
        allowed_tools=frozenset(),
        may_edit_tests=False,
    )
    return ws_dir, ws, executor, ctx


@pytest.mark.asyncio
async def test_fs_list_and_read(test_env: tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext]) -> None:
    ws_dir, ws, _, ctx = test_env

    # Create dummy files
    sub = ws_dir / "src"
    sub.mkdir()
    (sub / "app.py").write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
    (ws_dir / "README.md").write_text("Hello DevPilot\n", encoding="utf-8")

    list_tool = FsListTool(ws)
    res_list = await list_tool.run(ctx, {"path": ".", "depth": 2})
    assert res_list.ok
    assert "src/" in res_list.output
    assert "app.py" in res_list.output
    assert "README.md" in res_list.output

    # Read file
    read_tool = FsReadTool(ws)
    res_read = await read_tool.run(ctx, {"path": "src/app.py", "start": 2, "end": 3})
    assert res_read.ok
    assert "line 2" in res_read.output
    assert "line 3" in res_read.output
    assert "line 1" not in res_read.output

    # Read not found
    res_nf = await read_tool.run(ctx, {"path": "nonexistent.py"})
    assert not res_nf.ok
    assert res_nf.error_code == "NOT_FOUND"

    # Invalid line ranges
    res_inv = await read_tool.run(ctx, {"path": "src/app.py", "start": 5, "end": 2})
    assert not res_inv.ok
    assert res_inv.error_code == "INVALID_ARGS"


@pytest.mark.asyncio
async def test_fs_edit_and_write(test_env: tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext]) -> None:
    ws_dir, ws, _, ctx = test_env

    test_file = ws_dir / "calc.py"
    test_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    edit_tool = FsEditTool(ws)
    res_edit = await edit_tool.run(ctx, {"path": "calc.py", "old": "a - b", "new": "a + b"})
    assert res_edit.ok
    assert "return a + b" in test_file.read_text(encoding="utf-8")

    # Ambiguous match
    test_file.write_text("dup\ndup\n", encoding="utf-8")
    res_amb = await edit_tool.run(ctx, {"path": "calc.py", "old": "dup", "new": "unique"})
    assert not res_amb.ok
    assert res_amb.error_code == "AMBIGUOUS_MATCH"

    # Not found with closest line hint
    res_nf = await edit_tool.run(ctx, {"path": "calc.py", "old": "dupp", "new": "fixed"})
    assert not res_nf.ok
    assert res_nf.error_code == "NOT_FOUND"
    assert "dup" in (res_nf.error_message or "")

    # Write tool: new file
    write_tool = FsWriteTool(ws)
    res_write = await write_tool.run(ctx, {"path": "new.py", "content": "x = 1\n"})
    assert res_write.ok
    assert (ws_dir / "new.py").exists()

    # Refuse overwrite without overwrite flag
    res_ov_refuse = await write_tool.run(ctx, {"path": "new.py", "content": "x = 2\n"})
    assert not res_ov_refuse.ok
    assert res_ov_refuse.error_code == "POLICY_DENIED"

    # Allow overwrite with flag when < 200 lines
    res_ov_ok = await write_tool.run(ctx, {"path": "new.py", "content": "x = 2\n", "overwrite": True})
    assert res_ov_ok.ok
    assert (ws_dir / "new.py").read_text(encoding="utf-8") == "x = 2\n"

    # Refuse overwrite if >= 200 lines
    big_file = ws_dir / "big.py"
    big_file.write_text("\n".join(f"line_{i}" for i in range(250)), encoding="utf-8")
    res_big = await write_tool.run(ctx, {"path": "big.py", "content": "overwrite", "overwrite": True})
    assert not res_big.ok
    assert res_big.error_code == "POLICY_DENIED"
    assert ">= 200" in (res_big.error_message or "")


@pytest.mark.asyncio
async def test_fs_test_assertion_protection(
    test_env: tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext],
) -> None:
    ws_dir, ws, _, ctx = test_env

    test_file = ws_dir / "test_app.py"
    test_file.write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")

    edit_tool = FsEditTool(ws)
    # Attempt to weaken assert without may_edit_tests
    res_edit = await edit_tool.run(
        ctx, {"path": "test_app.py", "old": "assert 1 == 1", "new": "assert True"}
    )
    assert not res_edit.ok
    assert res_edit.error_code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # With may_edit_tests=True
    ctx_allowed = ToolContext(
        mission_id="M-TEST-001",
        agent_id="sentinel",
        mode_id="sentinel.triage",
        task_key="T1",
        workspace_ref="main",
        allowed_tools=frozenset(),
        may_edit_tests=True,
    )
    res_edit_allowed = await edit_tool.run(
        ctx_allowed, {"path": "test_app.py", "old": "assert 1 == 1", "new": "assert True"}
    )
    assert res_edit_allowed.ok


@pytest.mark.asyncio
async def test_fs_write_probe(test_env: tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext]) -> None:
    _, _, _, ctx = test_env
    runs_dir = Path(os.environ.get("TEMP", "/tmp")) / "devpilot_test_runs"

    probe_tool = FsWriteProbeTool(runs_dir)
    res = await probe_tool.run(ctx, {"name": "probe_check.py", "content": "print('ok')\n"})
    assert res.ok
    probe_path = runs_dir / ctx.mission_id / "probes" / "probe_check.py"
    assert probe_path.exists()
    assert probe_path.read_text(encoding="utf-8") == "print('ok')\n"


@pytest.mark.asyncio
async def test_search_code_ripgrep_and_python_parity(
    test_env: tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext],
) -> None:
    ws_dir, ws, executor, ctx = test_env

    # Seed files with various search terms
    src = ws_dir / "pkg"
    src.mkdir(parents=True)
    (src / "mod1.py").write_text("def find_me():\n    return 'secret_value'\n", encoding="utf-8")
    (src / "mod2.py").write_text(
        "def another():\n    val = find_me()\n    return val\n", encoding="utf-8"
    )

    search_tool = SearchCodeTool(ws, executor)

    # 1. Pure Python fallback search
    search_tool.force_python_fallback = True
    res_python = await search_tool.run(ctx, {"pattern": "find_me"})
    assert res_python.ok
    assert res_python.fallback_used == "python_re_walker"
    py_lines = res_python.output.splitlines()

    # 2. Ripgrep search (if rg installed)
    search_tool.force_python_fallback = False
    res_rg = await search_tool.run(ctx, {"pattern": "find_me"})
    assert res_rg.ok
    rg_lines = res_rg.output.splitlines()

    # Check that search matches and outputs are identical
    assert len(py_lines) == 2
    assert "pkg/mod1.py:1: def find_me():" in py_lines
    assert "pkg/mod2.py:2: val = find_me()" in py_lines

    # Parity check: Python walker and ripgrep produce the exact same matches
    if res_rg.fallback_used is None:
        assert py_lines == rg_lines


@pytest.mark.asyncio
async def test_shell_run_policy(test_env: tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext]) -> None:
    _, ws, executor, ctx = test_env
    settings = load_settings(None)

    shell_tool = ShellRunTool(ws, executor, settings)

    # 1. Allowlisted command
    res = await shell_tool.run(ctx, {"argv": ["python", "-m", "pytest", "--version"]})
    assert res.ok
    assert "pytest" in res.output.lower()

    # 2. Metacharacter rejection
    res_meta = await shell_tool.run(ctx, {"argv": ["python", "-c", "import sys; print(1)"]})
    assert not res_meta.ok
    assert res_meta.error_code == "SHELL_METACHARACTER"

    # 3. Explicit deny or path jail
    res_deny = await shell_tool.run(ctx, {"argv": ["rm", "-rf", "/"]})
    assert not res_deny.ok
    assert res_deny.error_code in ("COMMAND_DENIED", "COMMAND_NOT_ALLOWLISTED", "PATH_OUTSIDE_WORKSPACE")

    # 4. Unknown non-allowlisted command
    res_un = await shell_tool.run(ctx, {"argv": ["unknown_tool_cmd", "test"]})
    assert not res_un.ok
    assert res_un.error_code == "COMMAND_NOT_ALLOWLISTED"


@pytest.mark.asyncio
async def test_register_all_and_stubs(
    test_env: tuple[Path, SimpleWorkspaces, LocalExecutor, ToolContext],
) -> None:
    ws_dir, ws, executor, ctx = test_env
    runs_dir = ws_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings(None)
    ledger = FileEvidenceLedger(runs_dir)
    gateway = DefaultToolGateway(ledger)

    tool_ctx = ToolRegistryContext(
        mission_id="M-TEST-001",
        settings=settings,
        workspaces=ws,
        executor=executor,
        ledger=ledger,
        runs_dir=runs_dir,
    )

    register_all(gateway, tool_ctx)

    # Verify that all 26 tools are registered
    assert len(gateway._tools) == 52  # 26 dotted + 26 underscore names

    # Test stubs return TOOL_UNAVAILABLE
    stub_tools = [
        "lab.differential",
        "lab.property",
        "lab.mutation",
        "lab.coverage",
        "lab.integrity",
        "debug.ddmin",
        "scan.taint",
        "search.symbols",
        "graph.callers",
    ]
    for st in stub_tools:
        tool = gateway.get_tool(st)
        assert tool is not None
        res = await tool.run(ctx, {})
        assert not res.ok
        assert res.error_code == "TOOL_UNAVAILABLE"
        assert res.error_message is not None
        assert "pending" in res.error_message.lower() or "not available" in res.error_message.lower()
