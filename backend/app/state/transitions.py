"""Authoritative mission lifecycle table (AGENTS.md §0.4). The only place transitions are defined."""
from __future__ import annotations

from .enums import TERMINAL_STATUSES
from .enums import MissionStatus as S

ALLOWED: dict[S, set[S]] = {
    S.CREATED: {S.PLANNING, S.PAUSED, S.CANCELLED},
    S.PLANNING: {S.AWAITING_HUMAN, S.EXECUTING, S.PAUSED, S.CANCELLED, S.FAILED},
    S.AWAITING_HUMAN: {S.PLANNING, S.EXECUTING, S.CANCELLED, S.FAILED},
    S.EXECUTING: {S.AWAITING_HUMAN, S.VERIFYING, S.PAUSED, S.CANCELLED, S.FAILED},
    S.VERIFYING: {S.EXECUTING, S.AWAITING_APPROVAL, S.PAUSED, S.CANCELLED, S.FAILED},
    S.AWAITING_APPROVAL: {S.COMPLETED, S.EXECUTING, S.REJECTED, S.CANCELLED},
    S.PAUSED: {S.CREATED, S.PLANNING, S.EXECUTING, S.VERIFYING, S.CANCELLED},
    S.COMPLETED: set(),
    S.REJECTED: set(),
    S.FAILED: set(),
    S.CANCELLED: set(),
}


class IllegalTransition(Exception):
    def __init__(self, src: S, dst: S):
        super().__init__(f"illegal transition {src} -> {dst}")
        self.src, self.dst = src, dst


def can_transition(src: S, dst: S) -> bool:
    return dst in ALLOWED[src]


def assert_transition(src: S, dst: S) -> None:
    if not can_transition(src, dst):
        raise IllegalTransition(src, dst)


def is_terminal(s: S) -> bool:
    return s in TERMINAL_STATUSES
