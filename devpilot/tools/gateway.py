"""DefaultToolGateway: Central policy enforcement, circuit breaking, and evidence pipeline.

Implements `ports.ToolGateway`. Every tool call passes through:
1. Tool naming mapping (API name `_` <-> internal `.`).
2. Mode permissions check (`ctx.allowed_tools`).
3. Chaos / tool disable check (`DEVPILOT_DISABLE_TOOLS`).
4. Required `rationale` presence verification.
5. Circuit breaker evaluation (trips after 3 consecutive failures).
6. Schema validation (`jsonschema`).
7. Execution policy check (path jail, command tier, metacharacters).
8. Execution via tool implementation or executor.
9. Secret redaction on all outputs (regex set from docs/07 §3).
10. Truncation for long outputs (first 60 + last 140 lines).
11. Recording in `FileEvidenceLedger` to produce verifiable SHA256 evidence.
12. Event dispatch (`TOOL_CALL`, `TOOL_RESULT`, `POLICY_DENIED`, `TOOL_UNAVAILABLE`, `CIRCUIT_OPENED`).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from devpilot.core.events import Event, EventType
from devpilot.core.models import Evidence
from devpilot.core.ports import EvidenceLedger, Tool, ToolContext, ToolResult, ToolSchema
from devpilot.tools.ledger import FileEvidenceLedger
from devpilot.tools.policy import PolicyDenied, redact_secrets

EventCallback = Callable[[Event], Any]


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


class DefaultToolGateway:
    """Tool execution gateway enforcing permissions, policy, and logging."""

    def __init__(
        self,
        ledger: EvidenceLedger | None = None,
        event_callback: EventCallback | None = None,
        disabled_tools: Sequence[str] = (),
    ) -> None:
        self.ledger: EvidenceLedger = ledger or FileEvidenceLedger()
        self.event_callback = event_callback
        self.circuit_breaker = CircuitBreaker(threshold=3)
        self._tools: dict[str, Tool] = {}
        self._disabled_tools = set(disabled_tools)

    def register(self, tool: Tool) -> None:
        """Register a tool implementation under its dotted name and underscore name."""
        dotted = tool.name.replace("_", ".")
        underscore = tool.name.replace(".", "_")
        self._tools[dotted] = tool
        self._tools[underscore] = tool

    def get_tool(self, name: str) -> Tool | None:
        """Look up tool by dotted or underscore name."""
        return self._tools.get(name) or self._tools.get(name.replace("_", ".")) or self._tools.get(name.replace(".", "_"))

    def _normalize_name(self, name: str) -> str:
        """Return canonical dotted internal name."""
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

            api_name = orig_schema.name.replace(".", "_")
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

        # 5. Tool lookup
        tool = self.get_tool(dotted_name)
        if not tool:
            return ToolResult(
                ok=False,
                tool=dotted_name,
                output="",
                error_code="TOOL_UNAVAILABLE",
                error_message=f"Tool {dotted_name!r} is not registered in gateway",
            )

        # 6. Schema validation
        try:
            # Validate against original schema + rationale
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

        # Emit TOOL_CALL event
        self._emit(
            EventType.TOOL_CALL,
            ctx,
            actor,
            {"tool": dotted_name, "args": args, "rationale": rationale},
            f"Call {dotted_name}: {rationale}",
        )

        # 7. Execute tool and catch policy exceptions or runtime errors
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

        # If execution succeeded, reset circuit breaker; otherwise record failure
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

        # 8. Secret Redaction
        sanitized_output = redact_secrets(raw_result.output)

        # 9. Truncation
        truncated_output, is_truncated = truncate_output(sanitized_output)

        # 10. Evidence Ledger Record
        evidence_draft = Evidence(
            id="E-0000",  # Will be assigned by ledger
            kind=tool.evidence_kind,
            tool=dotted_name,
            agent_id=actor,
            mode_id=ctx.mode_id,
            workspace_ref=ctx.workspace_ref,
            workspace_sha="0" * 40,
            summary=f"Tool {dotted_name} executed with status ok={raw_result.ok}",
            log_path="",
            sha256="",
            structured=raw_result.structured,
        )

        saved_evidence = await self.ledger.record(evidence_draft, sanitized_output)

        # 11. Emit TOOL_RESULT event
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
