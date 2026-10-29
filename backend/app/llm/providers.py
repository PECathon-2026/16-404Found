"""Live providers over httpx. NOT exercised against the real APIs in this repo's tests (no keys in CI);
the request/response mapping is unit-tested with canned payloads."""
from __future__ import annotations

import json
from typing import Any

import httpx

from .base import LLMError, LLMResponse, Msg, ToolCall, Usage, tool_name, wire_name


def _retryable(status: int, body: str) -> bool:
    """Rate limits and 5xx are worth retrying; an exhausted quota/credit balance is permanent (retrying only burns time)."""
    if status == 429 and any(w in body.lower() for w in ("insufficient", "quota", "credit", "billing")):
        return False
    return status in (408, 409, 429, 500, 502, 503, 529)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com", timeout: float = 90.0):
        self.api_key, self.model, self.base_url, self.timeout = api_key, model, base_url.rstrip("/"), timeout

    @staticmethod
    def build_body(model: str, system: str, messages: list[Msg], tools: list[dict[str, Any]], max_tokens: int, temperature: float) -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.text:
                    blocks.append({"type": "text", "text": m.text})
                blocks += [{"type": "tool_use", "id": c.id, "name": wire_name(c.name), "input": c.args} for c in m.tool_calls]
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": c} for i, _, c in m.results]})
        body: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": out}
        if tools:
            body["tools"] = [{"name": wire_name(t["name"]), "description": t["description"], "input_schema": t["input_schema"]} for t in tools]
        return body

    @staticmethod
    def parse(data: dict[str, Any], model: str) -> LLMResponse:
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        calls = [ToolCall(b["id"], tool_name(b["name"]), b.get("input", {})) for b in data.get("content", []) if b.get("type") == "tool_use"]
        u = data.get("usage", {})
        return LLMResponse(text, calls, Usage(u.get("input_tokens", 0), u.get("output_tokens", 0)), data.get("model", model), "anthropic")

    async def complete(self, *, system: str, messages: list[Msg], tools: list[dict[str, Any]], max_tokens: int, temperature: float, purpose: str) -> LLMResponse:
        body = self.build_body(self.model, system, messages, tools, max_tokens, temperature)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            try:
                r = await c.post(f"{self.base_url}/v1/messages", json=body, headers={
                    "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            except httpx.HTTPError as e:
                raise LLMError(f"anthropic transport error: {type(e).__name__}", retryable=True) from None
        if r.status_code >= 400:
            quota = False
            msg = f"anthropic HTTP {r.status_code}: {r.text[:200]}"
            try:
                d = r.json()
                if "error" in d and isinstance(d["error"], dict) and "message" in d["error"]:
                    t = d["error"]["message"]
                    if any(w in t.lower() for w in ("credit", "balance", "billing")):
                        msg = f"Anthropic credit balance is too low ($0 remaining). Add credits at console.anthropic.com or use a free Gemini/Groq key."
                        quota = True
                    else:
                        msg = f"Anthropic error: {t}"
            except Exception:
                pass
            raise LLMError(msg, retryable=_retryable(r.status_code, r.text), quota_exhausted=quota)
        return self.parse(r.json(), self.model)


class OpenAICompatProvider:
    """OpenAI, and anything speaking the chat-completions protocol (e.g. Gemini's OpenAI-compatible endpoint, Ollama)."""
    name = "openai_compat"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 90.0):
        self.api_key, self.model, self.base_url, self.timeout = api_key, model, base_url.rstrip("/"), timeout

    @staticmethod
    def build_body(model: str, system: str, messages: list[Msg], tools: list[dict[str, Any]], max_tokens: int, temperature: float) -> dict[str, Any]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.text or None}
                if m.tool_calls:
                    msg["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": wire_name(c.name), "arguments": json.dumps(c.args)}} for c in m.tool_calls]
                out.append(msg)
            else:
                out += [{"role": "tool", "tool_call_id": i, "content": c} for i, _, c in m.results]
        body: dict[str, Any] = {"model": model, "messages": out, "max_tokens": max_tokens, "temperature": temperature}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": wire_name(t["name"]), "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
        return body

    @staticmethod
    def parse(data: dict[str, Any], model: str) -> LLMResponse:
        msg = (data.get("choices") or [{}])[0].get("message", {})
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": c["function"].get("arguments", "")[:200]}
            calls.append(ToolCall(c["id"], tool_name(c["function"]["name"]), args))
        u = data.get("usage", {})
        return LLMResponse(msg.get("content") or "", calls, Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)), data.get("model", model), "openai_compat")

    async def complete(self, *, system: str, messages: list[Msg], tools: list[dict[str, Any]], max_tokens: int, temperature: float, purpose: str) -> LLMResponse:
        body = self.build_body(self.model, system, messages, tools, max_tokens, temperature)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            try:
                r = await c.post(f"{self.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {self.api_key}"})
            except httpx.HTTPError as e:
                raise LLMError(f"openai-compat transport error: {type(e).__name__}", retryable=True) from None
        if r.status_code >= 400:
            quota = False
            msg = f"openai-compat HTTP {r.status_code}: {r.text[:200]}"
            try:
                d = r.json()
                if "error" in d and isinstance(d["error"], dict) and "message" in d["error"]:
                    t = d["error"]["message"]
                    code = d["error"].get("code", "")
                    if any(w in t.lower() for w in ("credit", "quota", "billing")) or code == "credit_balance_exhausted":
                        msg = f"OpenAI credits exhausted ($0 balance remaining). Add credits at platform.openai.com/billing or configure a free Gemini/Groq key."
                        quota = True
                    else:
                        msg = f"OpenAI error: {t}"
            except Exception:
                pass
            raise LLMError(msg, retryable=_retryable(r.status_code, r.text), quota_exhausted=quota)
        return self.parse(r.json(), self.model)
