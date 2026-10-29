"""Tool interface + registry. Every call is validated, authorised, logged, redacted and evented (§A.5)."""
from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..common.ids import new_id, now_iso
from ..common.redact import redact
from ..db import tool_calls
from ..deps import Deps
from ..sandbox.runner import LocalJailRunner
from .permissions import is_allowed

EXCERPT_LIMIT = 4000


class ToolError(Exception):
    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


@dataclass
class ToolContext:
    deps: Deps
    mission_id: str
    agent_id: str
    workspace: Path
    runner: LocalJailRunner
    task_id: str | None = None
    task_kind: str | None = None
    execution_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    base_commit: str = ""
    allowed_tools: set[str] | None = None  # master may restrict tools per task
    current_tcl: str | None = None

    def __post_init__(self) -> None:
        # Resolve symlinks once (macOS: /var -> /private/var). The path jail returns resolved paths, so every
        # comparison against the workspace must use the resolved root too.
        self.workspace = Path(os.path.realpath(self.workspace))


class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    output_excerpt: str = ""
    output_ref: str | None = None
    tool_call_id: str = ""
    duration_ms: int = 0

    def for_model(self) -> str:
        import json

        body: dict[str, Any] = {"ok": self.ok}
        if self.error:
            body["error"] = self.error
        if self.data is not None:
            body["data"] = self.data
        return json.dumps(body, default=str)[:12000]


@dataclass
class ToolSpec:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]
    side_effects: str = "none"

    def json_schema(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        return {"name": self.name, "description": self.description, "input_schema": schema}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas_for(self, agent: str, names: list[str] | None = None) -> list[dict[str, Any]]:
        return [t.json_schema() for n, t in sorted(self._tools.items()) if is_allowed(agent, n) and (names is None or n in names)]

    async def call(self, ctx: ToolContext, name: str, raw_args: dict[str, Any]) -> ToolResult:
        d = ctx.deps
        tcl = new_id("tcl")
        started = time.monotonic()
        spec = self._tools.get(name)
        args_summary = _summarise_args(raw_args)

        def persist(status: str, error: dict[str, Any] | None, excerpt: str, ref: str | None, exit_code: int | None = None,
                    redactions: int = 0, sha: str | None = None, reason: str | None = None) -> None:
            d.db.insert(
                tool_calls, id=tcl, mission_id=ctx.mission_id, task_id=ctx.task_id, execution_id=ctx.execution_id,
                agent_id=ctx.agent_id, tool=name, args=_redact_args(raw_args), status=status, exit_code=exit_code,
                duration_ms=int((time.monotonic() - started) * 1000), output_excerpt=excerpt, output_ref=ref,
                output_sha256=sha, redactions=redactions, policy_reason=reason, started_at=now_iso(), ended_at=now_iso(),
            )

        if spec is None:
            err = {"code": "NOT_FOUND", "message": f"unknown tool {name!r}"}
            persist("ERROR", err, err["message"], None)
            return ToolResult(ok=False, error=err, output_excerpt=err["message"], tool_call_id=tcl)
        if not is_allowed(ctx.agent_id, name) or (ctx.allowed_tools is not None and name not in ctx.allowed_tools):
            reason = f"agent {ctx.agent_id!r} may not use {name}"
            return self._denied(ctx, tcl, name, args_summary, reason, persist, started)
        try:
            args = spec.args.model_validate(raw_args)
        except ValidationError as e:
            err = {"code": "INVALID_ARGS", "message": "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())[:600]}
            persist("ERROR", err, err["message"], None)
            return ToolResult(ok=False, error=err, output_excerpt=err["message"], tool_call_id=tcl)

        ctx.current_tcl = tcl
        d.bus.publish(ctx.mission_id, "tool.called", ctx.agent_id, {"tool_call_id": tcl, "agent_id": ctx.agent_id, "tool": name,
                                                                    "args_summary": args_summary}, task_id=ctx.task_id)
        try:
            data = await spec.handler(ctx, args)
            ok, err = True, None
        except ToolError as e:
            data, ok, err = None, False, {"code": e.code, "message": e.message, **e.extra}
        except Exception as e:  # noqa: BLE001 - never leak exceptions to agents
            data, ok, err = None, False, {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}"[:300]}
        dur = int((time.monotonic() - started) * 1000)

        if err and err["code"] == "POLICY_DENIED":
            return self._denied(ctx, tcl, name, args_summary, err["message"], persist, started, announce=False)

        import json

        full = json.dumps({"data": data, "error": err}, default=str, indent=1)
        full_red, nred = redact(full)
        data_red = json.loads(redact(json.dumps(data, default=str))[0]) if data is not None else None
        excerpt = full_red[:EXCERPT_LIMIT]
        ref = None
        if len(full_red) > EXCERPT_LIMIT:
            art = d.settings.artifacts_dir / ctx.mission_id
            art.mkdir(parents=True, exist_ok=True)
            p = art / f"{tcl}.txt"
            p.write_text(full_red)
            ref = str(p)
        sha = hashlib.sha256(full_red.encode()).hexdigest()
        exit_code = data.get("exit_code") if isinstance(data, dict) and isinstance(data.get("exit_code"), int) else None
        persist("OK" if ok else "ERROR", err, excerpt, ref, exit_code, nred, sha)
        evt = "tool.completed" if ok else "tool.failed"
        d.bus.publish(ctx.mission_id, evt, ctx.agent_id, {"tool_call_id": tcl, "agent_id": ctx.agent_id, "tool": name,
                      "args_summary": args_summary, "status": "OK" if ok else "ERROR", "exit_code": exit_code, "duration_ms": dur,
                      "error_code": (err or {}).get("code")}, task_id=ctx.task_id)
        return ToolResult(ok=ok, data=data_red, error=err, output_excerpt=excerpt, output_ref=ref, tool_call_id=tcl, duration_ms=dur)

    def _denied(self, ctx: ToolContext, tcl: str, name: str, args_summary: str, reason: str, persist: Callable[..., None],
                started: float, announce: bool = True) -> ToolResult:
        d = ctx.deps
        err = {"code": "POLICY_DENIED", "message": reason}
        persist("DENIED", err, reason, None, reason=reason)
        d.bus.publish(ctx.mission_id, "policy.denied", ctx.agent_id, {"tool": name, "reason": reason, "args_summary": args_summary,
                                                                    "tool_call_id": tcl}, task_id=ctx.task_id)
        return ToolResult(ok=False, error=err, output_excerpt=reason, tool_call_id=tcl, duration_ms=int((time.monotonic() - started) * 1000))


def _summarise_args(a: dict[str, Any]) -> str:
    parts = []
    for k, v in a.items():
        s = repr(v) if not isinstance(v, str) else v
        parts.append(f"{k}={redact(s[:80])[0]}")
    return ", ".join(parts)[:240]


def _redact_args(a: Any) -> Any:
    if isinstance(a, str):
        return redact(a[:4000])[0]
    if isinstance(a, dict):
        return {k: _redact_args(v) for k, v in a.items()}
    if isinstance(a, list):
        return [_redact_args(v) for v in a[:100]]
    return a
