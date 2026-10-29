"""Append-only history guard.

Preserved thinking binds each thinking block to the exact prefix it was produced under, so the
conversation sent to the API may only ever grow at the end. The AgentRuntime calls
``assert_append_only`` before each request in debug/test mode.
"""

from __future__ import annotations

from typing import Any


class HistoryEditedError(AssertionError):
    """Raised when a new message list does not start with the previous one, exactly."""


def assert_append_only(prev: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    if len(new) < len(prev):
        raise HistoryEditedError(f"history shrank from {len(prev)} to {len(new)} messages")
    for i, (a, b) in enumerate(zip(prev, new, strict=False)):
        if a != b:
            raise HistoryEditedError(f"message {i} was edited")
