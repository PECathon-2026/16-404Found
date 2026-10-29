"""Offline tests for the Anthropic adapter: pure request/response mapping and the stream loop."""

from __future__ import annotations

import logging
from typing import Any

import anthropic
import httpx
import pytest
from anthropic.types import Message

from devpilot.config import Settings
from devpilot.core.models import ModelTier
from devpilot.core.ports import LLMRequest, LLMResponse, PromptBlock, ToolSchema
from devpilot.llm.anthropic_adapter import AnthropicLLM, build_params, effort_for_budget, map_response
from devpilot.llm.pricing import cost_usd

OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"
SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def tool(name: str, cache: bool = False) -> ToolSchema:
    return ToolSchema(name=name, description=f"{name} tool", input_schema=SCHEMA, cache=cache)


def request(**kw: Any) -> LLMRequest:
    base: dict[str, Any] = {
        "tier": ModelTier.WORKHORSE,
        "system": [PromptBlock("sys")],
        "messages": [{"role": "user", "content": "hello"}],
        "tools": [],
    }
    base.update(kw)
    return LLMRequest(**base)


def message(content: list[dict[str, Any]], stop: str = "end_turn", **usage: Any) -> Message:
    u = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": None,
         "cache_creation_input_tokens": None}
    u.update(usage)
    return Message.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": OPUS,
        "content": content, "stop_reason": stop, "stop_sequence": None, "usage": u,
    })


# ---------------------------------------------------------------- build_params


def test_forced_tool_choice_rewritten_for_opus_and_sonnet() -> None:
    for model in (OPUS, SONNET):
        req = request(tools=[tool("fs_read"), tool("submit_plan")],
                      tool_choice={"type": "tool", "name": "submit_plan"})
        p = build_params(req, model)
        assert p["tool_choice"] == {"type": "auto"}
        by_name = {t["name"]: t for t in p["tools"]}
        assert by_name["submit_plan"]["strict"] is True
        assert by_name["submit_plan"]["input_schema"]["additionalProperties"] is False
        assert "strict" not in by_name["fs_read"]
        last = p["messages"][-1]
        assert last["role"] == "user"
        assert last["content"][-1] == {
            "type": "text", "text": "You must now call the tool submit_plan to submit your result."}
        assert last["content"][0] == {"type": "text", "text": "hello"}
    assert req.messages == [{"role": "user", "content": "hello"}]  # input untouched
    assert "additionalProperties" not in req.tools[1].input_schema


def test_forced_any_and_non_user_tail() -> None:
    req = request(tools=[tool("a"), tool("b")], tool_choice={"type": "any"},
                  messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": [
                      {"type": "text", "text": "ok"}]}])
    p = build_params(req, OPUS)
    assert p["tool_choice"] == {"type": "auto"}
    assert all(t["strict"] for t in p["tools"])
    assert p["messages"][-1]["role"] == "user"


def test_submit_tools_strict_even_when_not_forced_for_stable_tools_array() -> None:
    a = build_params(request(tools=[tool("submit_x")]), OPUS)
    b = build_params(request(tools=[tool("submit_x")], tool_choice={"type": "tool", "name": "submit_x"}), OPUS)
    assert a["tools"] == b["tools"]
    assert "tool_choice" not in a and b["tool_choice"] == {"type": "auto"}


def test_haiku_accepts_forced_tool_choice_unchanged() -> None:
    req = request(tools=[tool("submit_plan")], tool_choice={"type": "tool", "name": "submit_plan"})
    p = build_params(req, HAIKU)
    assert p["tool_choice"] == {"type": "tool", "name": "submit_plan"}
    assert "strict" not in p["tools"][0]
    assert p["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.parametrize(("budget", "effort"), [
    (None, "low"), (0, "low"), (4000, "low"), (4001, "medium"), (8000, "medium"),
    (8001, "high"), (12000, "high"), (12001, "xhigh"), (50000, "xhigh"),
])
def test_effort_mapping(budget: int | None, effort: str) -> None:
    assert effort_for_budget(budget) == effort
    p = build_params(request(thinking_budget=budget), OPUS)
    assert p["output_config"] == {"effort": effort}
    assert p["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_no_sampling_params_or_budget_tokens() -> None:
    p = build_params(request(thinking_budget=8000), HAIKU)
    for k in ("temperature", "top_p", "top_k"):
        assert k not in p
    assert "budget_tokens" not in p["thinking"]
    assert p["max_tokens"] == 8000  # respects request value exactly
    assert build_params(request(max_output_tokens=777), OPUS)["max_tokens"] == 777


def test_cache_markers_placed_on_flagged_blocks() -> None:
    req = request(system=[PromptBlock("a", cache=True), PromptBlock("b")],
                  tools=[tool("t1"), tool("t2", cache=True)])
    p = build_params(req, SONNET)
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in p["system"][1]
    assert "cache_control" not in p["tools"][0]
    assert p["tools"][1]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in p["tools"]] == ["t1", "t2"]


def test_more_than_four_breakpoints_keeps_last_four(caplog: pytest.LogCaptureFixture) -> None:
    msgs = [{"role": "user", "content": [{"type": "text", "text": "m", "cache_control": {"type": "ephemeral"}}]}]
    req = request(
        system=[PromptBlock("s1", cache=True), PromptBlock("s2", cache=True)],
        tools=[tool("t1", cache=True), tool("t2", cache=True)],
        messages=msgs,
    )
    with caplog.at_level(logging.WARNING):
        p = build_params(req, SONNET)
    marked = [t["name"] for t in p["tools"] if "cache_control" in t]
    marked += [s["text"] for s in p["system"] if "cache_control" in s]
    marked += [b["text"] for b in p["messages"][0]["content"] if "cache_control" in b]
    assert marked == ["t2", "s1", "s2", "m"]  # earliest (t1) dropped
    assert "dropped" in caplog.text
    assert "cache_control" in msgs[0]["content"][0]  # caller's messages not mutated


def test_fallbacks_params() -> None:
    for model in (OPUS, SONNET):
        p = build_params(request(), model)
        assert p["fallbacks"] == "default"
        assert p["betas"] == ["server-side-fallback-2026-07-01"]
    p = build_params(request(), HAIKU)
    assert "fallbacks" not in p
    assert "betas" not in p
    p = build_params(request(), OPUS, enable_fallbacks=False)
    assert "fallbacks" not in p
    assert "betas" not in p


def test_params_deterministic_and_history_unchanged() -> None:
    history = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hm", "signature": "SIG"},
            {"type": "tool_use", "id": "t1", "name": "fs_read", "input": {"p": "a"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    ]
    req = request(messages=history, tools=[tool("fs_read")])
    p1, p2 = build_params(req, OPUS), build_params(req, OPUS)
    assert p1 == p2
    assert p1["messages"] == history


# ---------------------------------------------------------------- map_response


def test_map_response_blocks_and_usage() -> None:
    msg = message(
        [
            {"type": "thinking", "thinking": "reasoning", "signature": "SIG=="},
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
            {"type": "tool_use", "id": "tu_1", "name": "fs_read", "input": {"path": "a.py", "n": 3}},
        ],
        stop="tool_use", input_tokens=1_000_000, output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000, cache_creation_input_tokens=1_000_000,
    )
    r = map_response(msg, OPUS, 123)
    assert r.text == "Hello world"
    assert r.thinking_summary == "reasoning"
    assert r.stop_reason == "tool_use"
    assert r.tool_uses[0].input == {"path": "a.py", "n": 3}
    assert r.usage.tokens_in == 1_000_000 and r.usage.tokens_cached_read == 1_000_000
    assert r.usage.tokens_cache_write == 1_000_000 and r.usage.latency_ms == 123
    assert r.usage.tokens_thinking == 0
    assert r.usage.cost_usd == pytest.approx(4.00 + 20.00 + 0.20 + 5.00)
    assert r.raw_assistant_content[0] == {"type": "thinking", "thinking": "reasoning", "signature": "SIG=="}
    assert [b["type"] for b in r.raw_assistant_content] == ["thinking", "text", "text", "tool_use"]


def test_map_response_none_cache_fields_and_empty_thinking() -> None:
    msg = message([{"type": "thinking", "thinking": "", "signature": "S"}, {"type": "text", "text": "hi"}])
    r = map_response(msg, OPUS, 5)
    assert r.thinking_summary is None
    assert r.usage.tokens_cached_read == 0 and r.usage.tokens_cache_write == 0
    assert r.raw_assistant_content[0] == {"type": "thinking", "thinking": "", "signature": "S"}


@pytest.mark.parametrize(("sdk", "ours"), [
    ("end_turn", "end_turn"), ("tool_use", "tool_use"), ("max_tokens", "max_tokens"),
    ("refusal", "refusal"), ("pause_turn", "other"), ("stop_sequence", "other"),
])
def test_stop_reason_mapping(sdk: str, ours: str) -> None:
    assert map_response(message([{"type": "text", "text": "x"}], stop=sdk), OPUS, 1).stop_reason == ours


def test_refusal_discards_content() -> None:
    msg = message([{"type": "text", "text": "partial"}], stop="refusal")
    r = map_response(msg, OPUS, 1)
    assert r.stop_reason == "refusal"
    assert r.text == "" and r.tool_uses == [] and r.raw_assistant_content == []


def test_cost_and_unknown_model(caplog: pytest.LogCaptureFixture) -> None:
    c = {"tokens_in": 1_000_000, "tokens_out": 1_000_000, "tokens_cached_read": 1_000_000,
         "tokens_cache_write": 1_000_000}
    assert cost_usd(SONNET, c) == pytest.approx(2.0 + 10.0 + 0.20 + 2.50)
    assert cost_usd(OPUS, c) == pytest.approx(4.0 + 20.0 + 0.20 + 5.0)
    assert cost_usd(HAIKU, {"tokens_in": 1_000_000, "tokens_out": 1_000_000}) > 0  # long-prompt card
    assert cost_usd(HAIKU, {"tokens_in": 10_000, "tokens_out": 10_000}) == pytest.approx(0.0010 + 0.0050)
    with caplog.at_level(logging.WARNING):
        assert cost_usd("mystery-model", c) == 0.0
    assert "mystery-model" in caplog.text


# ---------------------------------------------------------------- stream loop


class FakeStream:
    def __init__(self, deltas: list[str], final: Message | None, error: Exception | None) -> None:
        self._deltas, self._final, self._error = deltas, final, error

    async def __aenter__(self) -> FakeStream:
        if self._error:
            raise self._error
        return self

    async def __aexit__(self, *a: object) -> None:
        return None

    @property
    def text_stream(self) -> Any:
        async def gen() -> Any:
            for d in self._deltas:
                yield d
        return gen()

    async def get_final_message(self) -> Message:
        assert self._final is not None
        return self._final


class FakeEndpoint:
    def __init__(self, script: list[Any]) -> None:
        self.script, self.calls = script, []

    def stream(self, **params: Any) -> FakeStream:
        self.calls.append(params)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            return FakeStream([], None, step)
        return FakeStream(["Hel", "lo"], step, None)


class FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.messages = FakeEndpoint([])
        self.beta = type("B", (), {})()
        self.beta.messages = FakeEndpoint(script)


def status_error(code: int, kind: str) -> anthropic.APIStatusError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(code, request=req)
    return anthropic.APIStatusError(
        kind, response=resp, body={"type": "error", "error": {"type": kind, "message": kind}})


def llm(client: Any, **kw: Any) -> AnthropicLLM:
    return AnthropicLLM(Settings(), client=client, backoff_base_s=0.0, **kw)


async def test_stream_end_to_end() -> None:
    final = message([{"type": "text", "text": "Hello"}])
    client = FakeClient([final])
    out = [i async for i in llm(client).stream(request())]
    assert out[:2] == ["Hel", "lo"]
    assert isinstance(out[2], LLMResponse) and out[2].text == "Hello"
    sent = client.beta.messages.calls[0]  # opus/sonnet + fallbacks -> beta endpoint
    assert sent["model"] == SONNET and sent["fallbacks"] == "default"


async def test_non_beta_endpoint_when_no_beta_feature() -> None:
    final = message([{"type": "text", "text": "Hello"}])
    client = FakeClient([])
    client.messages = FakeEndpoint([final])
    r = await llm(client, enable_fallbacks=False).complete(request())
    assert r.text == "Hello" and len(client.messages.calls) == 1 and not client.beta.messages.calls


async def test_model_override_and_resolve() -> None:
    a = llm(FakeClient([message([{"type": "text", "text": "x"}])]))
    assert a.resolve(ModelTier.FRONTIER) == OPUS and a.resolve(ModelTier.FAST) == HAIKU
    client = FakeClient([message([{"type": "text", "text": "x"}])])
    await llm(client).complete(request(model_override="claude-sonnet-5-5-test"))
    assert client.beta.messages.calls[0]["model"] == "claude-sonnet-5-5-test"


async def test_retries_529_then_succeeds() -> None:
    final = message([{"type": "text", "text": "ok"}])
    client = FakeClient([status_error(529, "overloaded_error"), status_error(529, "overloaded_error"), final])
    r = await llm(client).complete(request())
    assert r.text == "ok" and len(client.beta.messages.calls) == 3


async def test_529_gives_up_after_three_retries() -> None:
    client = FakeClient([status_error(529, "overloaded_error") for _ in range(5)])
    with pytest.raises(anthropic.APIStatusError):
        await llm(client).complete(request())
    assert len(client.beta.messages.calls) == 4  # 1 try + 3 retries


@pytest.mark.parametrize("code", [400, 401, 403, 404])
async def test_no_retry_on_client_errors(code: int) -> None:
    client = FakeClient([status_error(code, "invalid_request_error"), message([])])
    with pytest.raises(anthropic.APIStatusError):
        await llm(client).complete(request())
    assert len(client.beta.messages.calls) == 1
