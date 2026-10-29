"""Record/replay wrapper around any ``LLMPort`` for deterministic, offline runs.

Cassette file: JSONL, one ``{key, request_summary, response}`` per line, in call order. The key is
the sha256 of the canonical JSON of the request (``sort_keys=True``) minus volatile fields
(``metadata`` carries trace ids). It is computed from the ``LLMRequest`` rather than from the built
API params so replay needs neither an inner adapter nor config; the tier (not the resolved model id)
is part of the key, so a cassette survives a model-mapping change.
Identical requests replay their recordings in order and then keep returning the last one.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from devpilot.core.models import LLMUsage, ModelTier
from devpilot.core.ports import LLMPort, LLMRequest, LLMResponse, ToolUse

CHUNK = 40


class CassetteMiss(LookupError):
    """Replay mode found no recording for a request."""


def request_key(req: LLMRequest) -> str:
    d = dataclasses.asdict(req)
    d.pop("metadata", None)  # volatile: mission/agent ids for tracing
    d["tier"] = req.tier.value
    blob = json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _summary(req: LLMRequest) -> dict[str, Any]:
    return {
        "tier": req.tier.value,
        "model_override": req.model_override,
        "n_messages": len(req.messages),
        "tools": [t.name for t in req.tools],
        "tool_choice": req.tool_choice,
        "agent": req.metadata.get("agent_id") or req.metadata.get("mode_id"),
    }


def response_to_dict(resp: LLMResponse) -> dict[str, Any]:
    return {
        "text": resp.text,
        "thinking_summary": resp.thinking_summary,
        "tool_uses": [dataclasses.asdict(t) for t in resp.tool_uses],
        "stop_reason": resp.stop_reason,
        "usage": resp.usage.model_dump(mode="json"),
        "raw_assistant_content": resp.raw_assistant_content,
    }


def response_from_dict(d: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        text=d["text"],
        thinking_summary=d["thinking_summary"],
        tool_uses=[ToolUse(**t) for t in d["tool_uses"]],
        stop_reason=d["stop_reason"],
        usage=LLMUsage.model_validate(d["usage"]),
        raw_assistant_content=d["raw_assistant_content"],
    )


class CassetteLLM:
    """``LLMPort`` that records to / replays from a JSONL cassette."""

    def __init__(self, inner: LLMPort | None, path: Path,
                 mode: Literal["record", "replay", "passthrough"]) -> None:
        if mode in ("record", "passthrough") and inner is None:
            raise ValueError(f"mode {mode!r} requires an inner LLMPort")
        self._inner = inner
        self._path = Path(path)
        self._mode = mode
        self._recordings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._served: dict[str, int] = defaultdict(int)
        if mode == "replay":
            self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    self._recordings[row["key"]].append(row["response"])

    def resolve(self, tier: ModelTier) -> str:
        if self._inner is not None:
            return self._inner.resolve(tier)
        return f"cassette-{tier.value}"

    def _replay(self, req: LLMRequest) -> LLMResponse:
        key = request_key(req)
        recs = self._recordings.get(key)
        if not recs:
            raise CassetteMiss(f"no recording for request {key[:12]} ({_summary(req)}) in {self._path}")
        i = min(self._served[key], len(recs) - 1)
        self._served[key] += 1
        return response_from_dict(recs[i])

    def _append(self, req: LLMRequest, resp: LLMResponse) -> None:
        row = {"key": request_key(req), "request_summary": _summary(req), "response": response_to_dict(resp)}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    async def complete(self, req: LLMRequest) -> LLMResponse:
        final: LLMResponse | None = None
        async for item in self.stream(req):
            if isinstance(item, LLMResponse):
                final = item
        assert final is not None
        return final

    async def stream(self, req: LLMRequest) -> AsyncIterator[str | LLMResponse]:
        if self._mode == "replay":
            resp = self._replay(req)
            for i in range(0, len(resp.text), CHUNK):
                yield resp.text[i : i + CHUNK]
            yield resp
            return
        assert self._inner is not None
        async for item in self._inner.stream(req):
            if isinstance(item, LLMResponse) and self._mode == "record":
                self._append(req, item)
            yield item
