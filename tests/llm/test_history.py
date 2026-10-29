"""Tests for the append-only history guard."""

from __future__ import annotations

import pytest

from devpilot.llm.history import HistoryEditedError, assert_append_only

A = {"role": "user", "content": "hi"}
B = {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "S"}]}
C = {"role": "user", "content": [{"type": "text", "text": "next"}]}


def test_append_and_equal_ok() -> None:
    assert_append_only([], [A])
    assert_append_only([A, B], [A, B])
    assert_append_only([A, B], [A, B, C])


def test_edit_shrink_reorder_raise() -> None:
    with pytest.raises(HistoryEditedError):
        assert_append_only([A, B], [A, {**B, "content": []}, C])
    with pytest.raises(HistoryEditedError):
        assert_append_only([A, B], [A])
    with pytest.raises(HistoryEditedError):
        assert_append_only([A, B], [B, A, C])
    with pytest.raises(HistoryEditedError):  # trailing block appended into an old message
        assert_append_only([A], [{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
