"""Unit tests for DefaultToolGateway, CircuitBreaker, and FileEvidenceLedger."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from devpilot.core.events import Event, EventType
from devpilot.core.models import Evidence, EvidenceKind
from devpilot.core.ports import ToolContext, ToolResult, ToolSchema
from devpilot.engine import modes
from devpilot.tools.gateway import DefaultToolGateway, truncate_output
from devpilot.tools.ledger import FileEvidenceLedger


class MockTool:
    """Configurable mock tool for gateway pipeline testing."""

    def __init__(
        self,
        name: str = "mock.test",
        should_fail: bool = False,
        fail_code: str = "EXECUTION_ERROR",
        output: str = "mock output",
        evidence_kind: EvidenceKind = EvidenceKind.TOOL_OUTPUT,
    ) -> None:
        self.name = name
        self.should_fail = should_fail
        self.fail_code = fail_code
        self.output = output
        self.evidence_kind = evidence_kind
        self.call_count = 0
        self.schema = ToolSchema(
            name=name.replace(".", "_"),
            description="Mock tool description",
            input_schema={
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                    "path": {"type": "string"},
                    "argv": {"type": "array", "items": {"type": "string"}},
                },
                "required": [],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        self.call_count += 1
        if self.should_fail:
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code=self.fail_code,
                error_message="Simulated mock failure",
            )
        return ToolResult(
            ok=True,
            tool=self.name,
            output=self.output,
        )


class MockWorkspaces:
    """Mock Workspaces port for tree_sha and path resolution."""

    def __init__(self, sha: str = "a" * 40, root_path: Path | None = None) -> None:
        self.sha = sha
        self.root_path = root_path or Path.cwd()
        self.tree_sha_calls = 0

    async def tree_sha(self, ref: str = "main") -> str:
        self.tree_sha_calls += 1
        return self.sha

    async def path(self, ref: str = "main") -> Path:
        return self.root_path


def _make_ctx(
    allowed_tools: Sequence[str] = ("mock.test", "mock.other"),
    workspace_ref: str = "main",
) -> ToolContext:
    return ToolContext(
        mission_id="M-test-01",
        agent_id="samurai#1",
        mode_id="samurai.implement",
        task_key="T1",
        workspace_ref=workspace_ref,
        allowed_tools=frozenset(allowed_tools),
    )


@pytest.mark.asyncio
async def test_gateway_schema_injects_rationale() -> None:
    """Tool schema must have rationale injected as a required property."""
    gateway = DefaultToolGateway()
    mock = MockTool("fs.edit")
    gateway.register(mock)

    schemas = gateway.schemas(["fs.edit"])
    assert len(schemas) == 1
    schema = schemas[0]
    assert schema.name == "fs_edit"
    assert "rationale" in schema.input_schema["properties"]
    assert "rationale" in schema.input_schema["required"]


@pytest.mark.asyncio
async def test_gateway_tool_lookup_normalization(tmp_path: Path) -> None:
    """Tools can be called with dotted or underscore notation interchangeably."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    mock = MockTool("fs.read")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.read"])
    # Execute with dotted name
    res1 = await gateway.execute(ctx, "fs.read", {"param": "val", "rationale": "read file"})
    assert res1.ok is True

    # Execute with underscore name
    res2 = await gateway.execute(ctx, "fs_read", {"param": "val", "rationale": "read file"})
    assert res2.ok is True


@pytest.mark.asyncio
async def test_gateway_mode_permissions_enforced(tmp_path: Path) -> None:
    """Calling tools outside allowed_tools is rejected with POLICY_DENIED."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    mock = MockTool("fs.write")
    gateway.register(mock)

    # Allowed only fs.read, trying to call fs.write
    ctx = _make_ctx(allowed_tools=["fs.read"])
    res = await gateway.execute(ctx, "fs.write", {"param": "data", "rationale": "write attempt"})
    assert res.ok is False
    assert res.error_code == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_gateway_rationale_is_mandatory(tmp_path: Path) -> None:
    """Calls without rationale parameter are rejected with INVALID_ARGS."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    mock = MockTool("mock.test")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["mock.test"])
    # Empty or missing rationale
    res1 = await gateway.execute(ctx, "mock.test", {"param": "val"})
    assert res1.ok is False
    assert res1.error_code == "INVALID_ARGS"

    res2 = await gateway.execute(ctx, "mock.test", {"param": "val", "rationale": "   "})
    assert res2.ok is False
    assert res2.error_code == "INVALID_ARGS"


@pytest.mark.asyncio
async def test_gateway_circuit_breaker(tmp_path: Path) -> None:
    """Circuit opens after 3 consecutive failures for a tool."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    failing_tool = MockTool("failing.tool", should_fail=True, fail_code="EXECUTION_ERROR")
    gateway.register(failing_tool)

    ctx = _make_ctx(allowed_tools=["failing.tool"])

    # 3 consecutive failures
    for _ in range(3):
        res = await gateway.execute(ctx, "failing.tool", {"param": "val", "rationale": "call"})
        assert res.ok is False
        assert res.error_code == "EXECUTION_ERROR"

    # 4th call trips circuit breaker immediately
    res_tripped = await gateway.execute(ctx, "failing.tool", {"param": "val", "rationale": "call"})
    assert res_tripped.ok is False
    assert res_tripped.error_code == "CIRCUIT_OPEN"
    assert "use fallback" in res_tripped.error_message.lower()


@pytest.mark.asyncio
async def test_gateway_chaos_disabled_tool(tmp_path: Path) -> None:
    """Tools disabled by configuration return TOOL_UNAVAILABLE."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger, disabled_tools=["mock.test"])
    mock = MockTool("mock.test")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["mock.test"])
    res = await gateway.execute(ctx, "mock.test", {"param": "val", "rationale": "searching"})
    assert res.ok is False
    assert res.error_code == "TOOL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_gateway_secret_redaction_in_output(tmp_path: Path) -> None:
    """Sensitive keys in tool output are masked before returning and recording."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    secret_text = "Retrieved key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
    mock = MockTool("fs.read", output=secret_text)
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.read"])
    res = await gateway.execute(ctx, "fs.read", {"param": "config.txt", "rationale": "fetch config"})
    assert res.ok is True
    assert "sk-ant-api03" not in res.output
    assert "[REDACTED]" in res.output


def test_output_truncation() -> None:
    """Long outputs are truncated keeping head and tail lines."""
    lines = [f"line {i}\n" for i in range(500)]
    long_output = "".join(lines)
    truncated, was_truncated = truncate_output(long_output, head_lines=60, tail_lines=140)
    assert was_truncated is True
    assert truncated.startswith("line 0\n")
    assert "truncated 300 lines" in truncated
    assert truncated.endswith("line 499\n")


@pytest.mark.asyncio
async def test_evidence_ledger_storage_and_integrity(tmp_path: Path) -> None:
    """Ledger stores raw logs, generates sequential IDs, and validates digests."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    mock = MockTool("fs.read", output="hello evidence ledger")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.read"])
    res1 = await gateway.execute(ctx, "fs.read", {"param": "1", "rationale": "first call"})
    assert res1.evidence_id == "E-0001"
    assert ledger.exists("E-0001") is True

    ev1 = ledger.get("E-0001")
    assert ev1.id == "E-0001"
    assert Path(ev1.log_path).exists()
    assert Path(ev1.log_path).read_text(encoding="utf-8") == "hello evidence ledger"

    res2 = await gateway.execute(ctx, "fs.read", {"param": "2", "rationale": "second call"})
    assert res2.evidence_id == "E-0002"
    assert ledger.exists("E-0002") is True


@pytest.mark.asyncio
async def test_gateway_emits_lifecycle_events(tmp_path: Path) -> None:
    """Gateway emits TOOL_CALL and TOOL_RESULT events to the event callback."""
    emitted: list[Event] = []

    def on_event(ev: Event) -> None:
        emitted.append(ev)

    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger, event_callback=on_event)
    mock = MockTool("fs.read", output="ok")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.read"])
    await gateway.execute(ctx, "fs.read", {"param": "p", "rationale": "test event emission"})

    assert len(emitted) == 2
    assert emitted[0].type == EventType.TOOL_CALL
    assert emitted[1].type == EventType.TOOL_RESULT
    assert emitted[0].payload["tool"] == "fs.read"
    assert emitted[1].payload["ok"] is True


# --------------------------------------------------------------------------------------
# R1-R8 and (a), (b) Regression Tests
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r2_evidence_bound_to_workspace_tree_sha(tmp_path: Path) -> None:
    """R2 regression: Evidence tree_sha is retrieved from Workspaces port."""
    ws = MockWorkspaces(sha="1" * 40)
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger, workspaces=ws)

    mock = MockTool("test.run", evidence_kind=EvidenceKind.TEST_RUN, output="tests passed")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["test.run"])
    res = await gateway.execute(ctx, "test.run", {"param": "x", "rationale": "run test"})
    assert res.ok is True
    ev = ledger.get(res.evidence_id)
    assert ev.workspace_sha == "1" * 40
    assert "unbound" not in res.structured

    # Without workspaces, unbound is flagged
    gateway_no_ws = DefaultToolGateway(ledger=FileEvidenceLedger(tmp_path / "other"))
    gateway_no_ws.register(mock)
    res_no_ws = await gateway_no_ws.execute(ctx, "test.run", {"param": "x", "rationale": "run test"})
    assert res_no_ws.structured.get("unbound") is True


@pytest.mark.asyncio
async def test_r3_api_name_mapping_roundtrip() -> None:
    """R3 regression: fs.write_probe maps to fs_write_probe and round-trips for all mode tools."""
    gateway = DefaultToolGateway()
    probe_tool = MockTool("fs.write_probe")
    gateway.register(probe_tool)

    # Lookup by dotted and api name
    assert gateway.get_tool("fs.write_probe") is probe_tool
    assert gateway.get_tool("fs_write_probe") is probe_tool

    # Schemas expose api name
    schemas = gateway.schemas(["fs.write_probe"])
    assert len(schemas) == 1
    assert schemas[0].name == "fs_write_probe"

    # Test roundtrip for all tool names across all modes
    mode_tools = set()
    for mode in modes.REGISTRY.values():
        mode_tools.update(mode.tools)

    for tool_name in mode_tools:
        dummy = MockTool(tool_name)
        gateway.register(dummy)
        api_name = dummy.name.replace(".", "_")
        assert gateway.get_tool(dummy.name) is dummy
        assert gateway.get_tool(api_name) is dummy


@pytest.mark.asyncio
async def test_r6_ask_tier_handling(tmp_path: Path) -> None:
    """R6 regression: Command in ask tier requires approval callback."""
    ledger = FileEvidenceLedger(tmp_path)

    # 1. Without approver -> Denied with APPROVAL_REQUIRED
    gateway = DefaultToolGateway(ledger=ledger)
    exec_tool = MockTool("shell.run")
    gateway.register(exec_tool)

    ctx = _make_ctx(allowed_tools=["shell.run"])
    res1 = await gateway.execute(
        ctx, "shell.run", {"argv": ["pip", "install", "pkg"], "rationale": "install"}
    )
    assert res1.ok is False
    assert res1.error_code == "APPROVAL_REQUIRED"

    # 2. With approver that rejects
    async def reject_approver(c: ToolContext, cmd: list[str]) -> bool:
        return False

    gateway_reject = DefaultToolGateway(ledger=ledger, approver=reject_approver)
    gateway_reject.register(exec_tool)
    res2 = await gateway_reject.execute(
        ctx, "shell.run", {"argv": ["pip", "install", "pkg"], "rationale": "install"}
    )
    assert res2.ok is False
    assert res2.error_code == "APPROVAL_DENIED"

    # 3. With approver that accepts
    async def accept_approver(c: ToolContext, cmd: list[str]) -> bool:
        return True

    gateway_accept = DefaultToolGateway(ledger=ledger, approver=accept_approver)
    gateway_accept.register(exec_tool)
    res3 = await gateway_accept.execute(
        ctx, "shell.run", {"argv": ["pip", "install", "pkg"], "rationale": "install"}
    )
    assert res3.ok is True


@pytest.mark.asyncio
async def test_r7_tool_call_args_redacted(tmp_path: Path) -> None:
    """R7 regression: Secrets in TOOL_CALL event args are redacted."""
    emitted: list[Event] = []

    def on_event(ev: Event) -> None:
        emitted.append(ev)

    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger, event_callback=on_event)
    mock = MockTool("fs.write")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.write"])
    secret_code = "SECRET_KEY = 'sk-ant-12345678901234567890'"
    await gateway.execute(
        ctx,
        "fs.write",
        {"param": secret_code, "rationale": "writing config file with secret"},
    )

    tool_call_events = [e for e in emitted if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1
    call_args = tool_call_events[0].payload["args"]
    assert "sk-ant" not in str(call_args)
    assert "[REDACTED]" in str(call_args)


@pytest.mark.asyncio
async def test_r8_gateway_level_prechecks(tmp_path: Path) -> None:
    """R8 regression: Gateway enforces path jail and command policy pre-checks."""
    ws = MockWorkspaces(root_path=tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger, workspaces=ws)

    mock = MockTool("fs.read")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.read"])
    # Traversal in path argument caught by gateway pre-check
    res = await gateway.execute(
        ctx, "fs.read", {"path": "../outside.txt", "rationale": "escape attempt"}
    )
    assert res.ok is False
    assert res.error_code == "PATH_OUTSIDE_WORKSPACE"


@pytest.mark.asyncio
async def test_item_a_evidence_ledger_numbers_per_mission(tmp_path: Path) -> None:
    """Item (a): FileEvidenceLedger assigns sequential IDs per mission across workspace refs."""
    ledger = FileEvidenceLedger(tmp_path, mission_id="M-01")

    ev_main = Evidence(
        id="",
        kind=EvidenceKind.TOOL_OUTPUT,
        tool="mock",
        agent_id="samurai",
        workspace_ref="main",
        workspace_sha="0" * 40,
        summary="",
        log_path="",
        sha256="",
    )
    rec1 = await ledger.record(ev_main, "out1")
    assert rec1.id == "E-0001"
    assert rec1.workspace_ref == "main"

    ev_baseline = Evidence(
        id="",
        kind=EvidenceKind.TEST_RUN,
        tool="test.run",
        agent_id="sentinel",
        workspace_ref="baseline",
        workspace_sha="0" * 40,
        summary="",
        log_path="",
        sha256="",
    )
    rec2 = await ledger.record(ev_baseline, "out2")
    assert rec2.id == "E-0002"
    assert rec2.workspace_ref == "baseline"


@pytest.mark.asyncio
async def test_item_b_unregistered_tool_emits_tool_unavailable(tmp_path: Path) -> None:
    """Item (b): Calling unregistered tool emits TOOL_UNAVAILABLE event."""
    emitted: list[Event] = []

    def on_event(ev: Event) -> None:
        emitted.append(ev)

    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger, event_callback=on_event)

    ctx = _make_ctx(allowed_tools=["nonexistent.tool"])
    res = await gateway.execute(
        ctx, "nonexistent.tool", {"param": "x", "rationale": "call missing tool"}
    )
    assert res.ok is False
    assert res.error_code == "TOOL_UNAVAILABLE"

    unavail_events = [e for e in emitted if e.type == EventType.TOOL_UNAVAILABLE]
    assert len(unavail_events) == 1
    assert unavail_events[0].payload["tool"] == "nonexistent.tool"
