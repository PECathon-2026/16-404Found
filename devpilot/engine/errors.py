"""Exceptions raised by the AgentRuntime. Each carries the ``mode_id`` and a human ``reason``."""

from __future__ import annotations


class ModeError(Exception):
    """Base class: a mode invocation ended without a valid submission."""

    def __init__(self, mode_id: str, reason: str) -> None:
        super().__init__(f"{mode_id}: {reason}")
        self.mode_id = mode_id
        self.reason = reason


class ModeFailed(ModeError):
    """Generic failure: repair rounds exhausted, nudges exhausted, wall clock, internal error."""


class ModeRefused(ModeError):
    """The model returned ``stop_reason == "refusal"``."""


class StepBudgetExceeded(ModeError):
    """``ModeLimits.max_steps`` model calls were used without a valid submission."""


class BudgetExceeded(ModeError):
    """The mission-level budget ratio reached 1.0 before a model call."""


class HiddenSliceError(AssertionError):
    """A ContextRecipe includes a slice its own ``hidden`` tuple forbids (information-hiding breach)."""
