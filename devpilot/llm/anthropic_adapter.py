"""Anthropic implementation of ``LLMPort`` for Claude Opus/Sonnet/Haiku 5.5.

API constraints this module designs around (see docs/llm-notes.md):

* Forced ``tool_choice`` 400s on Opus 5.5 / Sonnet 5.5 -> rewritten to ``auto`` + ``strict`` tool +
  a trailing instruction block (``build_params``).
* ``budget_tokens`` and sampling params 400 -> adaptive thinking, depth via ``output_config.effort``.
* Thinking blocks must be replayed byte-for-byte -> ``raw_assistant_content`` is the exact dump of
  the response blocks, and ``build_params`` never edits earlier turns (it works on a deep copy and
  only appends / drops ``cache_control`` markers).
* Refusals arrive as HTTP 200 ``stop_reason="refusal"`` -> checked before reading content.
* Server-side fallback (beta ``server-side-fallback-2026-07-01``) is requested for Opus/Sonnet only.

``build_params`` and ``map_response`` are pure so they can be tested without network.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import random
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import anthropic

from devpilot.config import Settings
from devpilot.core.models import LLMUsage, ModelTier
from devpilot.core.ports import LLMRequest, LLMResponse, ToolUse
from devpilot.llm.pricing import cost_usd, has_price

log = logging.getLogger(__name__)

MAX_CACHE_BREAKPOINTS = 4
FALLBACK_BETA = "server-side-fallback-2026-07-01"
SUBMIT_PREFIX = "submit_"

# Models that reject tool_choice type "tool"/"any" with a 400 (tool-use.md; model-migration.md).
_NO_FORCED_TOOL_PREFIXES = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-mythos-5-1")
# Models with server-side fallback. Haiku 5.5 has none and 400s on a fallback list.
_FALLBACK_PREFIXES = ("claude-opus-5-5", "claude-sonnet-5-5")

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]
Effort = Literal["low", "medium", "high", "xhigh"]


# --------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------


def effort_for_budget(thinking_budget: int | None) -> Effort:
    """Map the legacy ``thinking_budget`` (token count) to an ``output_config.effort`` level."""
    if thinking_budget is None or thinking_budget <= 4000:
        return "low"
    if thinking_budget <= 8000:
        return "medium"
    if thinking_budget <= 12000:
        return "high"
    return "xhigh"


def rejects_forced_tool_choice(model: str) -> bool:
    return model.startswith(_NO_FORCED_TOOL_PREFIXES)


def supports_fallbacks(model: str) -> bool:
    return model.startswith(_FALLBACK_PREFIXES)


def uses_beta(params: dict[str, Any]) -> bool:
    """Single place deciding the endpoint: the beta endpoint is used only when a beta feature is set."""
    return bool(params.get("betas"))


def _strictify(schema: Any) -> Any:
    """Return a copy with ``additionalProperties: false`` on every object schema (required by strict)."""
    if isinstance(schema, dict):
        out = {k: _strictify(v) for k, v in schema.items()}
        if (out.get("type") == "object" or "properties" in out) and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [_strictify(v) for v in schema]
    return schema


def _forced(tool_choice: dict[str, Any] | None) -> tuple[str, str | None] | None:
    if tool_choice and tool_choice.get("type") in ("tool", "any"):
        return str(tool_choice["type"]), tool_choice.get("name")
    return None


def submit_instruction(tool_name: str | None = None) -> dict[str, Any]:
    """The user text block that nudges the model to call a ``submit_*`` tool.

    Forced ``tool_choice`` is a 400 on Opus/Sonnet 5.5, so the AgentRuntime appends this block to its
    own history (permanently, so history stays append-only) before the request. The adapter never does.
    """
    if tool_name:
        return {"type": "text", "text": f"You must now call the tool {tool_name} to submit your result."}
    return {"type": "text", "text": "You must now call one of the available tools."}


def needs_submit_instruction(req: LLMRequest, model: str) -> bool:
    """True when ``req`` forces a tool and ``model`` will have it rewritten to ``auto``."""
    return _forced(req.tool_choice) is not None and rejects_forced_tool_choice(model)


def _trim_breakpoints(tools: list[dict[str, Any]], system: list[dict[str, Any]],
                      messages: list[dict[str, Any]]) -> int:
    """Keep only the last MAX_CACHE_BREAKPOINTS cache_control markers (render order). Returns #dropped."""
    holders: list[dict[str, Any]] = [t for t in tools if "cache_control" in t]
    holders += [s for s in system if "cache_control" in s]
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            holders += [b for b in content if isinstance(b, dict) and "cache_control" in b]
    excess = len(holders) - MAX_CACHE_BREAKPOINTS
    if excess <= 0:
        return 0
    # Message content is never altered (append-only history), so only tool/system markers are dropped.
    owned = {id(x) for x in (*tools, *system)}
    removable = [h for h in holders if id(h) in owned]
    dropped = 0
    for h in removable[:excess]:
        del h["cache_control"]
        dropped += 1
    return dropped


def build_params(req: LLMRequest, model: str, *, enable_fallbacks: bool = True) -> dict[str, Any]:
    """Translate an ``LLMRequest`` into keyword arguments for ``messages.stream``.

    Pure: no network, no mutation of ``req``; ``messages`` are passed through verbatim. A ``betas`` key is present only when the request
    needs the beta endpoint (see ``uses_beta``).
    """
    forced = _forced(req.tool_choice)
    rewrite = forced is not None and rejects_forced_tool_choice(model)
    forced_name = forced[1] if forced else None
    strict_models = rejects_forced_tool_choice(model)

    tools: list[dict[str, Any]] = []
    for t in req.tools:
        # submit_* tools are always strict on Opus/Sonnet 5.5 (not only on the forced turn) so the
        # `tools` array stays byte-identical across turns: editing it would invalidate replayed
        # thinking blocks and the prompt cache.
        strict = strict_models and (
            t.name.startswith(SUBMIT_PREFIX) or (rewrite and (forced_name is None or t.name == forced_name))
        )
        d: dict[str, Any] = {"name": t.name, "description": t.description}
        d["input_schema"] = _strictify(t.input_schema) if strict else copy.deepcopy(t.input_schema)
        if strict:
            d["strict"] = True
        if t.cache:
            d["cache_control"] = {"type": "ephemeral"}
        tools.append(d)

    system: list[dict[str, Any]] = []
    for b in req.system:
        sb: dict[str, Any] = {"type": "text", "text": b.text}
        if b.cache:
            sb["cache_control"] = {"type": "ephemeral"}
        system.append(sb)

    messages = copy.deepcopy(req.messages)

    tool_choice: dict[str, Any] | None = copy.deepcopy(req.tool_choice) if req.tool_choice else None
    if rewrite and forced is not None:
        tool_choice = {"type": "auto"}
        if req.tool_choice and "disable_parallel_tool_use" in req.tool_choice:
            tool_choice["disable_parallel_tool_use"] = req.tool_choice["disable_parallel_tool_use"]
        log.debug("forced tool_choice %s rewritten to auto for %s", req.tool_choice, model)

    dropped = _trim_breakpoints(tools, system, messages)
    if dropped:
        log.warning("%d cache breakpoints requested (max %d); dropped the %d earliest",
                    dropped + MAX_CACHE_BREAKPOINTS, MAX_CACHE_BREAKPOINTS, dropped)

    params: dict[str, Any] = {
        "model": model,
        "max_tokens": req.max_output_tokens,
        "messages": messages,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": effort_for_budget(req.thinking_budget)},
    }
    if system:
        params["system"] = system
    if tools:
        params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
    if enable_fallbacks and supports_fallbacks(model):
        params["betas"] = [FALLBACK_BETA]
        params["fallbacks"] = "default"
    return params


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _dump_block(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return copy.deepcopy(block)
    dumped: dict[str, Any] = block.model_dump(mode="json", exclude_none=True)
    return dumped


def map_response(message: Any, model: str, latency_ms: int) -> LLMResponse:
    """Convert an SDK ``Message`` (or ``BetaMessage``) into an ``LLMResponse``."""
    raw_reason = _get(message, "stop_reason")
    usage = _get(message, "usage")
    t_in = int(_get(usage, "input_tokens", 0) or 0)
    t_out = int(_get(usage, "output_tokens", 0) or 0)
    t_read = int(_get(usage, "cache_read_input_tokens", 0) or 0)
    t_write = int(_get(usage, "cache_creation_input_tokens", 0) or 0)
    details = _get(usage, "output_tokens_details")
    t_think = int(_get(details, "thinking_tokens", 0) or 0) if details is not None else 0
    actual_model = _get(message, "model")
    priced = actual_model if isinstance(actual_model, str) and has_price(actual_model) else model
    counts = {"tokens_in": t_in, "tokens_out": t_out, "tokens_cached_read": t_read,
              "tokens_cache_write": t_write}
    llm_usage = LLMUsage(
        model=actual_model if isinstance(actual_model, str) and actual_model else model,
        tokens_in=t_in, tokens_out=t_out, tokens_cached_read=t_read, tokens_cache_write=t_write,
        tokens_thinking=t_think, cost_usd=cost_usd(priced, counts), latency_ms=latency_ms,
    )

    if raw_reason == "refusal":
        # Check before touching content: partial output of a declined turn is discarded and must not
        # be appended to history.
        details_obj = _get(message, "stop_details")
        log.warning("model refused (category=%s)", _get(details_obj, "category") if details_obj else None)
        return LLMResponse(text="", thinking_summary=None, tool_uses=[], stop_reason="refusal",
                           usage=llm_usage, raw_assistant_content=[])

    # stop_sequence, pause_turn, model_context_window_exceeded, None -> "other"
    stop_reason: StopReason = raw_reason if raw_reason in ("end_turn", "tool_use", "max_tokens") else "other"

    texts: list[str] = []
    thoughts: list[str] = []
    tool_uses: list[ToolUse] = []
    raw: list[dict[str, Any]] = []
    for block in _get(message, "content", None) or []:
        raw.append(_dump_block(block))
        btype = _get(block, "type")
        if btype == "text":
            texts.append(_get(block, "text", "") or "")
        elif btype == "thinking":
            if t := _get(block, "thinking", ""):
                thoughts.append(t)
        elif btype == "tool_use":
            tool_uses.append(ToolUse(id=_get(block, "id"), name=_get(block, "name"),
                                     input=dict(_get(block, "input", None) or {})))
    return LLMResponse(
        text="".join(texts),
        thinking_summary="\n\n".join(thoughts) or None,
        tool_uses=tool_uses,
        stop_reason=stop_reason,
        usage=llm_usage,
        raw_assistant_content=raw,
    )


def _is_overloaded(exc: BaseException) -> bool:
    if not isinstance(exc, anthropic.APIStatusError):
        return False
    if exc.status_code == 529:
        return True
    body = exc.body
    return isinstance(body, dict) and (
        body.get("type") == "overloaded_error"
        or (isinstance(body.get("error"), dict) and body["error"].get("type") == "overloaded_error")
    )


# --------------------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------------------


class AnthropicLLM:
    """``LLMPort`` backed by the Anthropic Messages API (always streaming)."""

    def __init__(
        self,
        settings: Settings,
        client: anthropic.AsyncAnthropic | None = None,
        concurrency: int = 4,
        enable_fallbacks: bool = True,
        overload_retries: int = 3,
        backoff_base_s: float = 1.0,
    ) -> None:
        self._settings = settings
        self._client = client
        self._sem = asyncio.Semaphore(concurrency)
        self._enable_fallbacks = enable_fallbacks
        self._overload_retries = overload_retries
        self._backoff_base_s = backoff_base_s

    # -- port ------------------------------------------------------------------------
    def resolve(self, tier: ModelTier) -> str:
        return self._settings.models.resolve_tier(tier)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        final: LLMResponse | None = None
        async for item in self.stream(req):
            if isinstance(item, LLMResponse):
                final = item
        if final is None:  # pragma: no cover - stream always ends with a response
            raise RuntimeError("stream ended without a final response")
        return final

    async def stream(self, req: LLMRequest) -> AsyncIterator[str | LLMResponse]:
        model = req.model_override or self.resolve(req.tier)
        params = build_params(req, model, enable_fallbacks=self._enable_fallbacks)
        client = self._get_client()
        endpoint = client.beta.messages if uses_beta(params) else client.messages
        async with self._sem:
            attempt = 0
            while True:
                started = time.perf_counter()
                yielded = False
                try:
                    async with endpoint.stream(**params) as s:
                        async for delta in s.text_stream:
                            yielded = True
                            yield delta
                        message = await s.get_final_message()
                    break
                except anthropic.APIStatusError as exc:
                    # Retry only overloaded (529) and only before any text reached the caller;
                    # 400/401/403/404 and everything else propagate immediately.
                    if yielded or not _is_overloaded(exc) or attempt >= self._overload_retries:
                        raise
                    delay = self._backoff_base_s * (2**attempt) * (0.5 + random.random())
                    attempt += 1
                    log.warning("overloaded (529); retry %d/%d in %.2fs", attempt, self._overload_retries, delay)
                    await asyncio.sleep(delay)
        latency_ms = int((time.perf_counter() - started) * 1000)
        yield map_response(message, model, latency_ms)

    def _get_client(self) -> Any:
        if self._client is None:
            # The SDK reads ANTHROPIC_API_KEY from the environment itself; we never touch it.
            self._client = anthropic.AsyncAnthropic(max_retries=4)
        return self._client
