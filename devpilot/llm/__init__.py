"""LLM adapters: the Anthropic reference implementation of ``LLMPort`` plus test doubles.

* ``AnthropicLLM``  - real adapter (streaming, caching, adaptive thinking, refusals, fallbacks).
* ``CassetteLLM``   - record/replay wrapper for deterministic offline runs.
* ``ScriptedLLM``   - scripted fake for unit tests of other packets.
"""

from __future__ import annotations

from devpilot.llm.anthropic_adapter import (
    AnthropicLLM,
    build_params,
    effort_for_budget,
    map_response,
    needs_submit_instruction,
    submit_instruction,
)
from devpilot.llm.cassette import CassetteLLM, CassetteMiss
from devpilot.llm.fake import ScriptedLLM, make_response
from devpilot.llm.history import HistoryEditedError, assert_append_only
from devpilot.llm.pricing import cost_usd

__all__ = [
    "AnthropicLLM",
    "CassetteLLM",
    "CassetteMiss",
    "HistoryEditedError",
    "ScriptedLLM",
    "assert_append_only",
    "build_params",
    "cost_usd",
    "effort_for_budget",
    "make_response",
    "map_response",
    "needs_submit_instruction",
    "submit_instruction",
]
