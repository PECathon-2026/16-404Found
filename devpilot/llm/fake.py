"""Scripted ``LLMPort`` fake for tests of other packets (no network, no API key)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from devpilot.core.models import LLMUsage, ModelTier
from devpilot.core.ports import LLMRequest, LLMResponse, ToolUse


def make_response(
    text: str = "",
    *,
    tool_uses: list[ToolUse] | None = None,
    stop_reason: str | None = None,
    thinking_summary: str | None = None,
    model: str = "scripted",
    tokens_in: int = 10,
    tokens_out: int = 5,
) -> LLMResponse:
    """Build an ``LLMResponse`` with a consistent ``raw_assistant_content`` for scripts."""
    uses = tool_uses or []
    raw: list[dict[str, Any]] = []
    if text:
        raw.append({"type": "text", "text": text})
    raw += [{"type": "tool_use", "id": u.id, "name": u.name, "input": u.input} for u in uses]
    reason = stop_reason or ("tool_use" if uses else "end_turn")
    return LLMResponse(
        text=text, thinking_summary=thinking_summary, tool_uses=uses,
        stop_reason=reason,  # type: ignore[arg-type]
        usage=LLMUsage(model=model, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0, latency_ms=1),
        raw_assistant_content=raw,
    )


class ScriptedLLM:
    """Returns scripted responses in order; records every request in ``.requests``."""

    def __init__(self, responses: list[LLMResponse | Callable[[LLMRequest], LLMResponse]]) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    def resolve(self, tier: ModelTier) -> str:
        return f"scripted-{tier.value}"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        if len(self.requests) > len(self._responses):
            raise RuntimeError(
                f"ScriptedLLM exhausted: {len(self.requests)} requests but only {len(self._responses)} responses"
            )
        item = self._responses[len(self.requests) - 1]
        return item(req) if callable(item) else item

    async def stream(self, req: LLMRequest) -> AsyncIterator[str | LLMResponse]:
        resp = await self.complete(req)
        if resp.text:
            yield resp.text
        yield resp
