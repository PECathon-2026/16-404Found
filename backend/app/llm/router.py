"""Model routing (ARCHITECTURE.md §I, MVP subset): per-mission provider selection, no hardcoded model ids,
fallback to the next configured provider on retryable errors, token/cost ledger with budget enforcement."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..common.ids import new_id, now_iso
from ..config import Settings
from ..db import model_calls
from ..deps import Deps
from .base import BudgetExceeded, LLMError, LLMProvider, LLMResponse, Msg
from .providers import AnthropicProvider, OpenAICompatProvider
from .scripted import ScriptedLLM

DEFAULT_LIMITS = {"max_tokens": 400_000, "max_cost_usd": 2.0}


class LLMRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._scripted: dict[str, ScriptedLLM] = {}

    # ---- provider discovery
    def live_providers(self) -> list[LLMProvider]:
        s, out = self.settings, []
        if s.anthropic_api_key and s.anthropic_model:
            out.append(AnthropicProvider(s.anthropic_api_key, s.anthropic_model))
        if s.openai_api_key and s.openai_model:
            out.append(OpenAICompatProvider(s.openai_api_key, s.openai_model, s.openai_base_url))
        return out

    def describe(self) -> dict[str, Any]:
        s = self.settings
        return {
            "providers": [
                {"id": "anthropic", "available": bool(s.anthropic_api_key and s.anthropic_model),
                 "reason": None if (s.anthropic_api_key and s.anthropic_model) else "set ANTHROPIC_API_KEY and ANTHROPIC_MODEL"},
                {"id": "openai_compat", "available": bool(s.openai_api_key and s.openai_model),
                 "reason": None if (s.openai_api_key and s.openai_model) else "set OPENAI_API_KEY and OPENAI_MODEL (and OPENAI_BASE_URL)"},
                {"id": "scripted", "available": True, "reason": None},
            ],
            "models": {"anthropic": s.anthropic_model or None, "openai_compat": s.openai_model or None},
            "live_available": bool(self.live_providers()),
        }

    def register_script(self, mission_id: str, script: dict[str, list[dict[str, Any]]]) -> ScriptedLLM:
        self._scripted[mission_id] = ScriptedLLM(script)
        return self._scripted[mission_id]

    def scripted(self, mission_id: str) -> ScriptedLLM | None:
        return self._scripted.get(mission_id)

    def enabled_for(self, mission: dict[str, Any], role: str) -> bool:
        if mission.get("mode") == "scripted":
            sc = self._scripted.get(mission["id"])
            return bool(sc and sc.has(role))
        return bool(self.live_providers())

    # ---- calls
    async def complete(self, deps: Deps, mission: dict[str, Any], role: str, execution_id: str | None, *, system: str,
                       messages: list[Msg], tools: list[dict[str, Any]], max_tokens: int = 4096, temperature: float = 0.2) -> LLMResponse:
        self.check_budget(deps, mission["id"])
        providers: list[Any]
        if mission.get("mode") == "scripted":
            sc = self._scripted.get(mission["id"])
            if sc is None:
                raise LLMError("scripted mission has no script registered")
            providers = [sc]
        else:
            providers = self.live_providers()
            if not providers:
                raise LLMError("no live model provider configured (set ANTHROPIC_API_KEY+ANTHROPIC_MODEL or OPENAI_API_KEY+OPENAI_MODEL)")
        last: Exception | None = None
        for i, p in enumerate(providers):
            for attempt in range(3 if mission.get("mode") != "scripted" else 1):
                t0 = time.monotonic()
                try:
                    r = await p.complete(system=system, messages=messages, tools=tools, max_tokens=max_tokens, temperature=temperature, purpose=role)
                except LLMError as e:
                    self._record(deps, mission["id"], execution_id, p, role, None, int((time.monotonic() - t0) * 1000), "ERROR")
                    last = e
                    if e.retryable and attempt < 2:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    break
                self._record(deps, mission["id"], execution_id, p, role, r, int((time.monotonic() - t0) * 1000), "OK",
                             fallback_from=providers[i - 1].name if i else None)
                return r
        raise LLMError(f"all providers failed: {last}")

    def _record(self, deps: Deps, mid: str, exe: str | None, p: Any, role: str, r: LLMResponse | None, ms: int, status: str,
                fallback_from: str | None = None) -> None:
        tin, tout = (r.usage.tokens_in, r.usage.tokens_out) if r else (0, 0)
        deps.db.insert(model_calls, id=new_id("mdl"), mission_id=mid, execution_id=exe, provider=p.name, model=getattr(p, "model", ""),
                       purpose=role, tokens_in=tin, tokens_out=tout, cost_usd=0.0, latency_ms=ms, status=status, created_at=now_iso())
        if r:
            deps.state.bump(mid, "tokens_used", tin + tout)
            m = deps.state.mission(mid)
            limit = (m["config"].get("limits") or {}).get("max_tokens", DEFAULT_LIMITS["max_tokens"])
            if m["tokens_used"] >= 0.8 * limit and not (m["config"].get("_budget_warned")):
                deps.state.update_mission(mid, config={**m["config"], "_budget_warned": True})
                deps.bus.publish(mid, "budget.warning", "system", {"resource": "tokens", "used": m["tokens_used"], "limit": limit,
                                                                  "pct": round(100 * m["tokens_used"] / limit)})

    def check_budget(self, deps: Deps, mid: str) -> None:
        m = deps.state.mission(mid)
        limit = (m["config"].get("limits") or {}).get("max_tokens", DEFAULT_LIMITS["max_tokens"])
        if m["tokens_used"] >= limit:
            raise BudgetExceeded(f"token budget exhausted ({m['tokens_used']}/{limit})")
