"""Mission runner: drives the graph in the background, resumes interrupts, pause/cancel. One graph thread per mission."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.types import Command

from ..deps import Deps
from ..llm.router import LLMRouter
from ..state.enums import TERMINAL_STATUSES
from ..state.enums import MissionStatus as S
from ..tools.base import ToolRegistry
from .orchestrator import Orchestrator

log = logging.getLogger("devpilot.runner")


class MissionRunner:
    def __init__(self, deps: Deps, registry: ToolRegistry, router: LLMRouter, checkpointer: Any):
        self.deps = deps
        self.pause_events: dict[str, asyncio.Event] = {}
        self.orch = Orchestrator(deps, registry, router, self.pause_events)
        self.graph = self.orch.build(checkpointer)
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.sem = asyncio.Semaphore(deps.settings.max_concurrent_missions)

    def _cfg(self, mid: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": mid}, "recursion_limit": 600}

    def start(self, mid: str) -> None:
        self._spawn(mid, {"mission_id": mid})

    def resume(self, mid: str, value: dict[str, Any]) -> None:
        self._spawn(mid, Command(resume=value))

    def _spawn(self, mid: str, payload: Any) -> None:
        t = self.tasks.get(mid)
        if t and not t.done():
            raise RuntimeError("mission is already running")
        self.tasks[mid] = asyncio.create_task(self._drive(mid, payload))

    async def _drive(self, mid: str, payload: Any) -> None:
        async with self.sem:
            try:
                await self.graph.ainvoke(payload, self._cfg(mid))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - a crashed graph must surface as FAILED, never hang silently
                log.exception("mission %s crashed", mid)
                self.orch._fail(mid, f"internal error: {type(e).__name__}: {str(e)[:200]}")

    async def wait(self, mid: str, timeout: float = 300.0) -> None:
        t = self.tasks.get(mid)
        if t:
            await asyncio.wait_for(asyncio.shield(t), timeout)

    # ---- controls
    def pause(self, mid: str) -> None:
        s = self.deps.state
        s.set_status(mid, S.PAUSED, "paused by the user", actor="human")
        self.pause_events.setdefault(mid, asyncio.Event()).clear()

    def unpause(self, mid: str) -> None:
        s = self.deps.state
        m = s.mission(mid)
        s.set_status(mid, S(m["status_before_pause"] or S.EXECUTING), "resumed", actor="human")
        self.pause_events.setdefault(mid, asyncio.Event()).set()

    def cancel(self, mid: str) -> None:
        s = self.deps.state
        m = s.mission(mid)
        if S(m["status"]) in TERMINAL_STATUSES:
            return
        s.set_status(mid, S.CANCELLED, "cancelled by the user", actor="human")
        self.orch._outcome(mid, "CANCELLED", "cancelled by the user")
        ev = self.pause_events.get(mid)
        if ev:
            ev.set()
        t = self.tasks.get(mid)
        if t and not t.done():
            t.cancel()
