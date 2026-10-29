"""Agent runtime: bounded tool-calling loop + execution bookkeeping (T3.07)."""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..common.ids import new_id, now_iso
from ..db import agent_executions
from ..deps import Deps
from ..llm.base import BudgetExceeded, LLMError, Msg
from ..llm.router import LLMRouter
from ..tools.base import ToolContext, ToolRegistry

T = TypeVar("T", bound=BaseModel)


@dataclass
class Execution:
    id: str
    result: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"
    error: str | None = None


@dataclass
class LoopOutcome:
    ok: bool
    result: Any = None
    error: str | None = None
    tool_call_ids: list[str] = field(default_factory=list)
    messages: list[Msg] = field(default_factory=list)
    tool_calls_made: int = 0


class AgentRuntime:
    def __init__(self, deps: Deps, registry: ToolRegistry, router: LLMRouter):
        self.deps, self.registry, self.router = deps, registry, router

    @asynccontextmanager
    async def execution(self, mission_id: str, agent_id: str, task_id: str | None = None, attempt: int = 1) -> AsyncIterator[Execution]:
        exe = Execution(new_id("exe"))
        self.deps.db.insert(agent_executions, id=exe.id, mission_id=mission_id, task_id=task_id, agent_id=agent_id, attempt=attempt,
                            status="RUNNING", result=None, error=None, started_at=now_iso(), ended_at=None, tokens_in=0, tokens_out=0, cost_usd=0.0)
        self.deps.bus.publish(mission_id, "agent.started", agent_id, {"agent_id": agent_id, "execution_id": exe.id, "task_id": task_id,
                                                                     "attempt": attempt}, task_id=task_id)
        try:
            yield exe
        except BudgetExceeded as e:
            exe.status, exe.error = "ERROR", str(e)
            raise
        except Exception as e:  # noqa: BLE001
            exe.status, exe.error = "ERROR", f"{type(e).__name__}: {e}"[:400]
            raise
        finally:
            self.deps.db.update(agent_executions, exe.id, status=exe.status, result=exe.result or None, error=exe.error, ended_at=now_iso())
            self.deps.bus.publish(mission_id, "agent.finished", agent_id, {"agent_id": agent_id, "execution_id": exe.id, "status": exe.status,
                                                                          "error": exe.error, "task_id": task_id}, task_id=task_id)

    async def loop(self, ctx: ToolContext, *, role: str, system: str, user: str, tool_names: list[str], result_name: str,
                   result_desc: str, result_model: type[T], max_tool_calls: int = 30, max_seconds: float = 300.0,
                   messages: list[Msg] | None = None) -> LoopOutcome:
        mission = self.deps.state.mission(ctx.mission_id)
        schema = result_model.model_json_schema()
        schema.pop("title", None)
        tools = self.registry.schemas_for(role, tool_names) + [{"name": result_name, "description": result_desc, "input_schema": schema}]
        msgs = list(messages or []) + [Msg("user", user)]
        out = LoopOutcome(ok=False, messages=msgs)
        started = time.monotonic()
        nudges = 0
        for _turn in range(max_tool_calls + 8):
            if time.monotonic() - started > max_seconds:
                out.error = f"agent exceeded {max_seconds:.0f}s"
                return out
            if self.deps.state.mission(ctx.mission_id)["status"] in ("CANCELLED",):
                out.error = "mission cancelled"
                return out
            try:
                resp = await self.router.complete(self.deps, mission, role, ctx.execution_id, system=system, messages=msgs, tools=tools)
            except (LLMError, BudgetExceeded) as e:
                out.error = str(e)
                return out
            msgs.append(Msg("assistant", resp.text, resp.tool_calls))
            if not resp.tool_calls:
                nudges += 1
                if nudges > 2:
                    out.error = "agent stopped without submitting a result"
                    return out
                msgs.append(Msg("user", f"Continue with tools if needed, otherwise call {result_name} now."))
                continue
            results: list[tuple[str, str, str]] = []
            done: Any = None
            for call in resp.tool_calls:
                if call.name == result_name:
                    try:
                        done = result_model.model_validate(call.args)
                        results.append((call.id, call.name, "accepted"))
                    except ValidationError as e:
                        results.append((call.id, call.name, f"invalid result: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}"))
                    continue
                if out.tool_calls_made >= max_tool_calls:
                    results.append((call.id, call.name, "tool-call budget exhausted: call " + result_name))
                    continue
                if "__invalid_json__" in call.args:
                    results.append((call.id, call.name, "arguments were not valid JSON"))
                    continue
                r = await self.registry.call(ctx, call.name, call.args)
                out.tool_calls_made += 1
                out.tool_call_ids.append(r.tool_call_id)
                results.append((call.id, call.name, f'<untrusted_data source="tool:{call.name}">{r.for_model()}</untrusted_data>'))
            msgs.append(Msg("tool_results", "", [], results))
            if done is not None:
                out.ok, out.result = True, done
                return out
        out.error = "agent exceeded its turn budget"
        return out
