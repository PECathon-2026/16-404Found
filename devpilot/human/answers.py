"""Scripted human channel for eval and CI runs.

The answers file is JSON keyed by gate name::

    {"clarification": "show", "escalation": "accept_partial", "apply": "approve"}

A value is a string, a ``{"choice": ..., "free_text": ...}`` object, or a list of either (consumed in
order, the last one repeating) for gates that fire more than once. A string that names one of the
prompt's options (by key, case-insensitively) is the *choice*; anything else is *free text*.

A gate with no answer never approves anything: ``apply`` is rejected and other gates are cancelled,
so a scripted run cannot hang or silently ship a change.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from devpilot.core.models import HumanDecision, HumanPrompt

log = logging.getLogger(__name__)

_CANCEL_KEYS = ("cancel", "abort", "reject", "accept_partial")


class AnswersFileError(ValueError):
    """The answers file is missing or malformed."""


class AnswersFileHumanChannel:
    """``ports.HumanChannel`` that answers every prompt from a JSON file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AnswersFileError(f"cannot read answers file {self.path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise AnswersFileError(f"{self.path}: top level must be an object keyed by gate")
        self._answers: dict[str, list[Any]] = {
            str(gate): list(val) if isinstance(val, list) else [val] for gate, val in raw.items()
        }
        self._used: dict[str, int] = {}
        self.asked: list[HumanPrompt] = []

    def _next(self, gate: str) -> Any | None:
        queue = self._answers.get(gate)
        if not queue:
            return None
        i = self._used.get(gate, 0)
        self._used[gate] = i + 1
        return queue[min(i, len(queue) - 1)]

    @staticmethod
    def _split(prompt: HumanPrompt, answer: Any) -> tuple[str | None, str | None]:
        if isinstance(answer, dict):
            choice = answer.get("choice")
            text = answer.get("free_text")
            return (None if choice is None else str(choice)), (None if text is None else str(text))
        text = str(answer).strip()
        for opt in prompt.options:
            if opt.key.lower() == text.lower():
                return opt.key, None
        return None, text

    @staticmethod
    def _fallback(prompt: HumanPrompt) -> str | None:
        """The safe choice when the file has no answer: never approve."""
        keys = {o.key for o in prompt.options}
        if prompt.gate == "apply" and "reject" in keys:
            return "reject"
        return next((k for k in _CANCEL_KEYS if k in keys), None)

    async def ask(self, prompt: HumanPrompt) -> HumanDecision:
        self.asked.append(prompt)
        answer = self._next(prompt.gate)
        if answer is None:
            choice, text = self._fallback(prompt), None
            log.warning("answers file has no answer for gate %r; using safe default %r", prompt.gate, choice)
        else:
            choice, text = self._split(prompt, answer)
        return HumanDecision(
            id=f"HD-{prompt.id}", prompt_id=prompt.id, choice=choice, free_text=text, source="answers_file"
        )
