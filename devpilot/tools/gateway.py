"""DefaultToolGateway: Central policy enforcement, circuit breaking, and evidence pipeline.

Implements `ports.ToolGateway`. Every tool call passes through:
1. Tool naming mapping (API name `_` <-> internal `.`).
2. Mode permissions check (`ctx.allowed_tools`).
3. Chaos / tool disable check (`DEVPILOT_DISABLE_TOOLS`).
4. Mandatory rationale presence verification.
5. Circuit breaker evaluation (trips after 3 consecutive failures).
6. Tool registration check (emits TOOL_UNAVAILABLE if missing).
7. Schema validation (`jsonschema`).
8. Execution pre-checks (path jail, command tier & forbidden flags).
9. Execution via tool implementation or executor with workspace tree_sha tracking.
10. Secret redaction on all outputs (and TOOL_CALL arguments).
11. Truncation for long outputs (first 60 + last 140 lines).
12. Recording in `FileEvidenceLedger` to produce verifiable SHA256 evidence.
13. Event dispatch (`TOOL_CALL`, `TOOL_RESULT`, `POLICY_DENIED`, `TOOL_UNAVAILABLE`, `CIRCUIT_OPENED`).
"""

from __future__ import annotations

import contextlib
import os
import shlex
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from devpilot.core.events import Event, EventType
from devpilot.core.models import Evidence, EvidenceKind
from devpilot.core.ports import EvidenceLedger, Tool, ToolContext, ToolResult, ToolSchema, Workspaces
from devpilot.tools.ledger import FileEvidenceLedger
from devpilot.tools.policy import CommandPolicy, PolicyDenied, redact_secrets, resolve_in_workspace

EventCallback = Callable[[Event], Any]

CODE_BOUND_KINDS: frozenset[EvidenceKind] = frozenset(
    {
        EvidenceKind.TEST_RUN,
        EvidenceKind.PROBE_RUN,
        EvidenceKind.PROPERTY_RUN,
        EvidenceKind.DIFFERENTIAL_RUN,
        EvidenceKind.MUTATION_RUN,
        EvidenceKind.COVERAGE,
        EvidenceKind.DIFF,
    }
)


class CircuitBreaker:
    """Tracks consecutive tool failures and opens circuit after reaching threshold."""

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self._consecutive_failures: dict[str, int] = {}
        self._open_circuits: set[str] = set()

    def is_open(self, tool_name: str) -> bool:
        return tool_name in self._open_circuits

    def record_success(self, tool_name: str) -> None:
        self._consecutive_failures[tool_name] = 0

    def record_failure(self, tool_name: str) -> bool:
        """Record failure and return True if circuit just transitioned to open."""
        count = self._consecutive_failures.get(tool_name, 0) + 1
        self._consecutive_failures[tool_name] = count
        if count >= self.threshold and tool_name not in self._open_circuits:
            self._open_circuits.add(tool_name)
            return True
        return False

    def reset(self) -> None:
        self._consecutive_failures.clear()
        self._open_circuits.clear()


def truncate_output(text: str, head_lines: int = 60, tail_lines: int = 140) -> tuple[str, bool]:
    """Truncate output keeping the first `head_lines` and last `tail_lines` if excessive."""
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if total <= (head_lines + tail_lines):
        return text, False

    kept = lines[:head_lines]
    skipped = total - head_lines - tail_lines
    kept.append(f"\n... [truncated {skipped} lines; full output preserved in evidence log] ...\n\n")
    kept.extend(lines[-tail_lines:])
    return "".join(kept), True


def _redact_value(val: Any) -> Any:
    """Recursively redact secrets in strings within nested structures."""
    if isinstance(val, str):
        return redact_secrets(val)
    if isinstance(val, dict):
        return {k: _redact_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_redact_value(x) for x in val]
    return val


class DefaultToolGateway:
    """Tool execution gateway enforcing permissions, policy, and logging."""

    def __init__(
        self,
        ledger: EvidenceLedger | None = None,
        event_callback: EventCallback | None = None,
        disabled_tools: Sequence[str] = (),
        workspaces: Workspaces | None = None,
        approver: Callable[[ToolContext, list[str]], Awaitable[bool]] | None = None,
        policy: CommandPolicy | None = None,
    ) -> None:
        self.ledger: EvidenceLedger = ledger or FileEvidenceLedger()
        self.event_callback = event_callback
        self.circuit_breaker = CircuitBreaker(threshold=3)
        self.workspaces = workspaces
        self.approver = approver
        self.policy = policy or CommandPolicy()
        self._tools: dict[str, Tool] = {}
        self._api_to_dotted: dict[str, str] = {}
        self._dotted_to_api: dict[str, str] = {}
        from devpilot.engine import modes
        for mode in modes.REGISTRY.values():
            for t in mode.tools:
                api = t.replace(".", "_")
                self._api_to_dotted[api] = t
                self._dotted_to_api[t] = api
        self._disabled_tools = set(disabled_tools)

    def register(self, tool: Tool) -> None:
        """Register a tool implementation under its dotted name and underscore name."""
        dotted = tool.name
        api_name = tool.name.replace(".", "_")
        self._tools[dotted] = tool
        self._tools[api_name] = tool
        self._dotted_to_api[dotted] = api_name
        self._api_to_dotted[api_name] = dotted

    def get_tool(self, name: str) -> Tool | None:
        """Look up tool by dotted or underscore name."""
        if name in self._api_to_dotted:
            return self._tools.get(self._api_to_dotted[name])
        return self._tools.get(name)

    def _normalize_name(self, name: str) -> str:
        """Return canonical dotted internal name."""
        if name in self._api_to_dotted:
            return self._api_to_dotted[name]
        return name.replace("_", ".")

    def _is_disabled(self, name: str) -> bool:
        """Check if tool is disabled via config or DEVPILOT_DISABLE_TOOLS."""
        dotted = self._normalize_name(name)
        if dotted in self._disabled_tools:
            return True
        env_disabled = os.environ.get("DEVPILOT_DISABLE_TOOLS", "")
        if env_disabled:
            items = [x.strip() for x in env_disabled.split(",") if x.strip()]
            if dotted in items or name in items:
                return True
        return False

    def _emit(
        self,
        event_type: EventType,
        ctx: ToolContext | None,
        actor: str,
        payload: dict[str, Any],
        summary: str = "",
    ) -> None:
        if self.event_callback:
            event = Event(
                seq=0,
                mission_id=ctx.mission_id if ctx else "global",
                type=event_type,
                actor=actor,
                mode_id=ctx.mode_id if ctx else None,
                task_key=ctx.task_key if ctx else None,
                payload=payload,
                summary=summary,
            )
            self.event_callback(event)

    def schemas(self, tool_names: Sequence[str]) -> list[ToolSchema]:
        """Return ToolSchema definitions for requested tools, injecting required rationale."""
        schemas_list: list[ToolSchema] = []
        for name in tool_names:
            tool = self.get_tool(name)
            if not tool:
                continue

            orig_schema = tool.schema
            input_schema = dict(orig_schema.input_schema)
            props = dict(input_schema.get("properties", {}))
            props["rationale"] = {
                "type": "string",
                "description": "One sentence explaining why this tool is invoked (recorded in run log).",
            }
            required = list(input_schema.get("required", []))
            if "rationale" not in required:
                required.append("rationale")

            input_schema["properties"] = props
            input_schema["required"] = required

            api_name = self._dotted_to_api.get(tool.name, tool.name.replace(".", "_"))
            schemas_list.append(
                ToolSchema(
                    name=api_name,
                    description=orig_schema.description,
                    input_schema=input_schema,
                    cache=orig_schema.cache,
                )
            )
        return schemas_list

    async def execute(self, ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool through the security, circuit-breaking, and auditing pipeline."""
        dotted_name = self._normalize_name(name)
        actor = ctx.agent_id

        # 1. Chaos / Disabled tool check
        if self._is_disabled(dotted_name):
            self._emit(
                EventType.TOOL_UNAVAILABLE,
                ctx,
                actor,
                {"tool": dotted_name, "reason": "Disabled by configuration / chaos"},
                f"Tool {dotted_name} unavailable",
            )
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="TOOL_UNAVAILABLE",
                error_message=f"Tool {dotted_name!r} is disabled or unavailable",
            )

        # 2. Permitted tools check (mode least-privilege)
        if dotted_name not in ctx.allowed_tools:
            self._emit(
                EventType.POLICY_DENIED,
                ctx,
                actor,
                {"tool": dotted_name, "reason": f"Tool not in allowed_tools for mode {ctx.mode_id}"},
                f"Tool {dotted_name} policy denied",
            )
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="POLICY_DENIED",
                error_message=f"Tool {dotted_name!r} is not permitted for mode {ctx.mode_id}",
            )

        # 3. Circuit breaker check
        if self.circuit_breaker.is_open(dotted_name):
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="CIRCUIT_OPEN",
                error_message=f"Circuit for tool {dotted_name!r} is open due to repeated failures; use fallback",
            )

        # 4. Mandatory rationale parameter check
        rationale = args.get("rationale")
        if not rationale or not str(rationale).strip():
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="INVALID_ARGS",
                error_message="Missing required parameter: 'rationale'",
            )

        # 5. Tool lookup (b: emit TOOL_UNAVAILABLE when missing)
        tool = self.get_tool(dotted_name)
        if not tool:
            self._emit(
                EventType.TOOL_UNAVAILABLE,
                ctx,
                actor,
                {"tool": dotted_name, "reason": f"Tool {dotted_name!r} is not registered in gateway"},
                f"Tool {dotted_name} unavailable",
            )
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="TOOL_UNAVAILABLE",
                error_message=f"Tool {dotted_name!r} is not registered in gateway",
            )

        # 6. Schema validation
        try:
            schema_props = dict(tool.schema.input_schema.get("properties", {}))
            schema_props["rationale"] = {"type": "string"}
            schema_req = list(tool.schema.input_schema.get("required", []))
            if "rationale" not in schema_req:
                schema_req.append("rationale")
            full_schema = {
                **tool.schema.input_schema,
                "properties": schema_props,
                "required": schema_req,
            }
            jsonschema.validate(instance=args, schema=full_schema)
        except jsonschema.ValidationError as err:
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="INVALID_ARGS",
                error_message=f"Schema validation error: {err.message}",
            )

        # 7. Gateway-level pre-checks for paths and command arguments (R8)
        ws_path: Path
        if self.workspaces is not None:
            try:
                ws_path = await self.workspaces.path(ctx.workspace_ref)
            except Exception:
                ws_path = Path.cwd()
        else:
            ws_path = Path.cwd()

        try:
            if "path" in args and isinstance(args["path"], str):
                resolve_in_workspace(ws_path, args["path"])
            if "paths" in args and isinstance(args["paths"], list):
                for p in args["paths"]:
                    if isinstance(p, str):
                        resolve_in_workspace(ws_path, p)
            if "selector" in args or "selectors" in args:
                sels = args.get("selector") or args.get("selectors")
                if isinstance(sels, str):
                    sels = [sels]
                if isinstance(sels, list):
                    for s in sels:
                        if isinstance(s, str):
                            candidate = s.split("::", 1)[0]
                            if "/" in candidate or "\\" in candidate or candidate.endswith(".py"):
                                resolve_in_workspace(ws_path, candidate)
            if "argv" in args or "command" in args:
                cmd = args.get("argv") or args.get("command")
                if isinstance(cmd, str):
                    cmd = shlex.split(cmd)
                if isinstance(cmd, list) and cmd:
                    cls = self.policy.classify(cmd, caller_role=ctx.mode_id, workspace=ws_path)
                    if cls == "ask":
                        if self.approver is not None:
                            approved = await self.approver(ctx, cmd)
                            if not approved:
                                return ToolResult(
                                    ok=False,
                                    tool=dotted_name,
                                    output="",
                                    error_code="APPROVAL_DENIED",
                                    error_message=f"Command approval was rejected for {cmd[0]}",
                                )
                        else:
                            raise PolicyDenied(
                                "APPROVAL_REQUIRED",
                                f"Command requires approval but no approver is configured: {' '.join(cmd)}",
                            )
        except PolicyDenied as pd:
            self._emit(
                EventType.POLICY_DENIED,
                ctx,
                actor,
                {"tool": dotted_name, "code": pd.code, "message": pd.message},
                f"Policy denied on {dotted_name}: {pd.message}",
            )
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code=pd.code,
                error_message=pd.message,
            )

        # 8. Emit TOOL_CALL event with secrets redacted in args (R7)
        redacted_args = _redact_value(args)
        self._emit(
            EventType.TOOL_CALL,
            ctx,
            actor,
            {"tool": dotted_name, "args": redacted_args, "rationale": rationale},
            f"Call {dotted_name}: {rationale}",
        )

        # 9. Workspace tree_sha before execution (R2)
        tree_sha_before = "0" * 40
        if self.workspaces is not None:
            with contextlib.suppress(Exception):
                tree_sha_before = await self.workspaces.tree_sha(ctx.workspace_ref)

        # 10. Execute tool and catch policy exceptions or runtime errors
        try:
            raw_result = await tool.run(ctx, args)
        except PolicyDenied as pd:
            self._emit(
                EventType.POLICY_DENIED,
                ctx,
                actor,
                {"tool": dotted_name, "code": pd.code, "message": pd.message},
                f"Policy denied on {dotted_name}: {pd.message}",
            )
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code=pd.code,
                error_message=pd.message,
            )
        except TimeoutError:
            tripped = self.circuit_breaker.record_failure(dotted_name)
            if tripped:
                self._emit(
                    EventType.CIRCUIT_OPENED,
                    ctx,
                    actor,
                    {"tool": dotted_name},
                    f"Circuit opened for {dotted_name}",
                )
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="TIMEOUT",
                error_message=f"Tool {dotted_name!r} execution timed out",
            )
        except Exception as exc:
            tripped = self.circuit_breaker.record_failure(dotted_name)
            if tripped:
                self._emit(
                    EventType.CIRCUIT_OPENED,
                    ctx,
                    actor,
                    {"tool": dotted_name},
                    f"Circuit opened for {dotted_name}",
                )
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="EXECUTION_ERROR",
                error_message=str(exc),
            )

        # Reset or update circuit breaker
        if raw_result.ok:
            self.circuit_breaker.record_success(dotted_name)
        else:
            if raw_result.error_code in ("TIMEOUT", "EXECUTION_ERROR", "CRASH", "TOOL_UNAVAILABLE"):
                tripped = self.circuit_breaker.record_failure(dotted_name)
                if tripped:
                    self._emit(
                        EventType.CIRCUIT_OPENED,
                        ctx,
                        actor,
                        {"tool": dotted_name},
                        f"Circuit opened for {dotted_name}",
                    )

        # 11. Workspace tree_sha after execution (R2)
        tree_sha_after = tree_sha_before
        if self.workspaces is not None:
            with contextlib.suppress(Exception):
                tree_sha_after = await self.workspaces.tree_sha(ctx.workspace_ref)
                if tree_sha_after != tree_sha_before:
                    raw_result.structured["workspace_changed_during_run"] = True
        else:
            raw_result.structured["unbound"] = True

        workspace_sha = tree_sha_after

        # 12. Secret Redaction
        sanitized_output = redact_secrets(raw_result.output)

        # 13. Truncation
        truncated_output, is_truncated = truncate_output(sanitized_output)

        # 14. Evidence Ledger Record
        evidence_draft = Evidence(
            id="E-0000",
            kind=tool.evidence_kind,
            tool=dotted_name,
            agent_id=actor,
            mode_id=ctx.mode_id,
            workspace_ref=ctx.workspace_ref,
            workspace_sha=workspace_sha,
            summary=f"Tool {dotted_name} executed with status ok={raw_result.ok}",
            log_path="",
            sha256="",
            structured=raw_result.structured,
        )

        saved_evidence = await self.ledger.record(evidence_draft, sanitized_output)

        # 15. Emit TOOL_RESULT event
        self._emit(
            EventType.TOOL_RESULT,
            ctx,
            actor,
            {
                "tool": dotted_name,
                "ok": raw_result.ok,
                "evidence_id": saved_evidence.id,
                "error_code": raw_result.error_code,
            },
            f"Result from {dotted_name}: ok={raw_result.ok}",
        )

        return ToolResult(
            ok=raw_result.ok,
            tool=dotted_name,
            output=truncated_output,
            evidence_id=saved_evidence.id,
            error_code=raw_result.error_code,
            error_message=raw_result.error_message,
            fallback_used=raw_result.fallback_used,
            truncated=is_truncated or raw_result.truncated,
            structured=raw_result.structured,
        )
