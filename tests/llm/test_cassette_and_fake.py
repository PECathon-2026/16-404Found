"""Tests for CassetteLLM (record/replay) and ScriptedLLM."""

from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.core.models import ModelTier
from devpilot.core.ports import LLMRequest, LLMResponse, PromptBlock, ToolUse
from devpilot.llm.cassette import CassetteLLM, CassetteMiss
from devpilot.llm.fake import ScriptedLLM, make_response


def req(text: str = "hi", **meta: object) -> LLMRequest:
    return LLMRequest(tier=ModelTier.FAST, system=[PromptBlock("s")],
                      messages=[{"role": "user", "content": text}], tools=[], metadata=dict(meta))


async def test_record_then_replay_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "c" / "cassette.jsonl"
    long_text = "x" * 100
    resp = make_response(long_text, tool_uses=[ToolUse("t1", "submit_x", {"a": 1})],
                         thinking_summary="why")
    inner = ScriptedLLM([resp])
    rec = CassetteLLM(inner, path, "record")
    got = await rec.complete(req(run="A"))
    assert got == resp and path.is_file()

    rep = CassetteLLM(None, path, "replay")
    chunks: list[str] = []
    final: LLMResponse | None = None
    async for item in rep.stream(req(run="B")):  # metadata is volatile -> same key
        if isinstance(item, str):
            chunks.append(item)
        else:
            final = item
    assert [len(c) for c in chunks] == [40, 40, 20]
    assert "".join(chunks) == long_text
    assert final == resp
    assert final.usage.cost_usd == resp.usage.cost_usd


async def test_replay_duplicates_in_order_then_last(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    inner = ScriptedLLM([make_response("one"), make_response("two")])
    rec = CassetteLLM(inner, path, "record")
    await rec.complete(req())
    await rec.complete(req())
    rep = CassetteLLM(None, path, "replay")
    texts = [(await rep.complete(req())).text for _ in range(4)]
    assert texts == ["one", "two", "two", "two"]


async def test_replay_miss_raises(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    await CassetteLLM(ScriptedLLM([make_response("a")]), path, "record").complete(req("q1"))
    with pytest.raises(CassetteMiss):
        await CassetteLLM(None, path, "replay").complete(req("different"))
    with pytest.raises(CassetteMiss):  # missing file entirely
        await CassetteLLM(None, tmp_path / "none.jsonl", "replay").complete(req())


async def test_passthrough_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    r = await CassetteLLM(ScriptedLLM([make_response("a")]), path, "passthrough").complete(req())
    assert r.text == "a" and not path.exists()


def test_inner_required_for_record() -> None:
    with pytest.raises(ValueError):
        CassetteLLM(None, Path("x"), "record")


async def test_scripted_llm_order_callable_and_requests() -> None:
    seen = ScriptedLLM([
        make_response("first"),
        lambda r: make_response(f"echo:{r.messages[-1]['content']}"),
    ])
    assert (await seen.complete(req("a"))).text == "first"
    assert (await seen.complete(req("b"))).text == "echo:b"
    assert [r.messages[0]["content"] for r in seen.requests] == ["a", "b"]
    with pytest.raises(RuntimeError):
        await seen.complete(req())
    assert seen.resolve(ModelTier.FRONTIER) == "scripted-frontier"


async def test_scripted_stream_yields_text_then_response() -> None:
    s = ScriptedLLM([make_response("hello")])
    items = [i async for i in s.stream(req())]
    assert items[0] == "hello" and isinstance(items[1], LLMResponse)
