"""Unit tests for DefaultToolGateway, CircuitBreaker, and FileEvidenceLedger."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from devpilot.core.events import Event, EventType
from devpilot.core.models import EvidenceKind
from devpilot.core.ports import ToolContext, ToolResult, ToolSchema
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
    ) -> None:
        self.name = name
        self.should_fail = should_fail
        self.fail_code = fail_code
        self.output = output
        self.evidence_kind = EvidenceKind.TOOL_OUTPUT
        self.call_count = 0
        self.schema = ToolSchema(
            name=name.replace(".", "_"),
            description="Mock tool description",
            input_schema={
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                },
                "required": ["param"],
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


def _make_ctx(allowed_tools: Sequence[str] = ("mock.test", "mock.other")) -> ToolContext:
    return ToolContext(
        mission_id="M-test-01",
        agent_id="samurai#1",
        mode_id="samurai.implement",
        task_key="T1",
        workspace_ref="main",
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
async def test_gateway_allowed_tools_enforcement(tmp_path: Path) -> None:
    """Invoking a tool not in ctx.allowed_tools returns POLICY_DENIED."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    mock = MockTool("shell.run")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.read"])  # shell.run not allowed
    res = await gateway.execute(ctx, "shell.run", {"param": "ls", "rationale": "run command"})
    assert res.ok is False
    assert res.error_code == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_gateway_missing_rationale(tmp_path: Path) -> None:
    """Missing or empty rationale parameter returns INVALID_ARGS."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    mock = MockTool("fs.read")
    gateway.register(mock)

    ctx = _make_ctx(allowed_tools=["fs.read"])
    res = await gateway.execute(ctx, "fs.read", {"param": "data"})  # rationale missing
    assert res.ok is False
    assert res.error_code == "INVALID_ARGS"
    assert "rationale" in (res.error_message or "")


@pytest.mark.asyncio
async def test_gateway_circuit_breaker(tmp_path: Path) -> None:
    """3 consecutive failures open the circuit; subsequent calls return CIRCUIT_OPEN."""
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
    failing_tool = MockTool("flaky.tool", should_fail=True, fail_code="EXECUTION_ERROR")
    gateway.register(failing_tool)

    ctx = _make_ctx(allowed_tools=["flaky.tool"])

    # Calls 1, 2, 3 fail normally
    r1 = await gateway.execute(ctx, "flaky.tool", {"param": "a", "rationale": "try 1"})
    assert r1.ok is False
    assert r1.error_code == "EXECUTION_ERROR"

    r2 = await gateway.execute(ctx, "flaky.tool", {"param": "b", "rationale": "try 2"})
    assert r2.ok is False

    r3 = await gateway.execute(ctx, "flaky.tool", {"param": "c", "rationale": "try 3"})
    assert r3.ok is False
    assert gateway.circuit_breaker.is_open("flaky.tool") is True

    # Call 4 fails fast via circuit breaker
    r4 = await gateway.execute(ctx, "flaky.tool", {"param": "d", "rationale": "try 4"})
    assert r4.ok is False
    assert r4.error_code == "CIRCUIT_OPEN"
    # Underlying tool was not even called on attempt 4
    assert failing_tool.call_count == 3


@pytest.mark.asyncio
async def test_gateway_chaos_disabled_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tools listed in DEVPILOT_DISABLE_TOOLS return TOOL_UNAVAILABLE immediately."""
    monkeypatch.setenv("DEVPILOT_DISABLE_TOOLS", "search.code, mock.test")
    ledger = FileEvidenceLedger(tmp_path)
    gateway = DefaultToolGateway(ledger=ledger)
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
