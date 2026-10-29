"""ScriptedLLM: replays recorded/authored responses per role. Used for deterministic tests and the offline demo.
Missions using it are labelled `scripted` everywhere (never presented as live)."""
from __future__ import annotations

import itertools
from typing import Any

from .base import LLMResponse, Msg, ToolCall, Usage

_ids = itertools.count(1)


class ScriptedLLM:
    name = "scripted"
    model = "scripted"

    def __init__(self, script: dict[str, list[dict[str, Any]]]):
        self.script = {k: list(v) for k, v in script.items()}
        self.consumed: dict[str, int] = {}

    def has(self, role: str) -> bool:
        return bool(self.script.get(role))

    async def complete(self, *, system: str, messages: list[Msg], tools: list[dict[str, Any]], max_tokens: int, temperature: float, purpose: str) -> LLMResponse:
        queue = self.script.get(purpose, [])
        if not queue:
            return LLMResponse("(script exhausted)", [], Usage(10, 5), self.model, self.name)
        step = queue.pop(0)
        self.consumed[purpose] = self.consumed.get(purpose, 0) + 1
        calls = [ToolCall(f"call_{next(_ids)}", c["name"], c.get("args", {})) for c in step.get("tool_calls", [])]
        return LLMResponse(step.get("text", ""), calls, Usage(step.get("tokens_in", 120), step.get("tokens_out", 40)), self.model, self.name)
