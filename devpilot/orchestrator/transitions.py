"""Legal state-transition tables for missions and tasks (docs/04 section 1-2, extended by docs/11).

Pure data plus one guard function. The orchestrator calls ``assert_legal`` before it emits any
``STATE_CHANGED`` / ``TASK_STATE_CHANGED`` so an illegal move is a programming error that fails
loudly instead of silently corrupting the log.

Extensions over docs/04:

* ``INTEL`` (deterministic repo intelligence) and ``AUTHORING_ACCEPTANCE`` (spec-first tests) from docs/11.
* ``DECIDING -> CHECKING`` covers a decision that needs no new code.
* ``CHECKING -> CHECKING`` is the stale-verdict re-run.
* ``TESTING -> EXECUTING`` / ``DECIDING -> TESTING`` cover multi-task plans and tournaments.
* Tasks: ``TOURNAMENT`` (docs/11 section 5), ``BLOCKED/ESCALATED -> REWORK`` (a decision or human
  guidance resolves the block), ``TESTING -> TESTING`` is not allowed.
"""

from __future__ import annotations

from devpilot.core.models import MissionStatus as M
from devpilot.core.models import TaskStatus as T


class IllegalTransition(Exception):
    """A requested state change is not in the transition table."""


_TERMINAL: frozenset[M] = frozenset(s for s in M if s.terminal)

MISSION_TRANSITIONS: dict[M, frozenset[M]] = {
    M.CREATED: frozenset({M.INTEL, M.RECON}),
    M.INTEL: frozenset({M.RECON}),
    M.RECON: frozenset({M.ANALYZING}),
    M.ANALYZING: frozenset({M.CLARIFYING, M.PLANNING}),
    M.CLARIFYING: frozenset({M.ANALYZING}),
    M.PLANNING: frozenset({M.AWAITING_PLAN_APPROVAL, M.AUTHORING_ACCEPTANCE, M.EXECUTING}),
    M.AWAITING_PLAN_APPROVAL: frozenset({M.PLANNING, M.AUTHORING_ACCEPTANCE, M.EXECUTING}),
    M.AUTHORING_ACCEPTANCE: frozenset({M.EXECUTING}),
    M.EXECUTING: frozenset({M.TESTING, M.DECIDING}),
    M.TESTING: frozenset({M.DECIDING, M.CHECKING, M.EXECUTING}),
    M.DECIDING: frozenset({M.EXECUTING, M.RECON, M.PLANNING, M.CLARIFYING, M.TESTING, M.CHECKING}),
    M.CHECKING: frozenset({M.CHECKING, M.DECIDING, M.AWAITING_APPLY}),
    M.AWAITING_APPLY: frozenset({M.APPLYING, M.DECIDING}),
    M.APPLYING: frozenset(),
    M.REPORTING: frozenset(_TERMINAL),
}
# Any live state may be aborted, may jump to REPORTING (budget exhausted, human reject) or FAILED.
for _state in M:
    if _state.terminal:
        MISSION_TRANSITIONS[_state] = frozenset()
    else:
        MISSION_TRANSITIONS[_state] = MISSION_TRANSITIONS.get(_state, frozenset()) | {
            M.ABORTED,
            M.REPORTING,
            M.FAILED,
        }
MISSION_TRANSITIONS[M.REPORTING] = frozenset(_TERMINAL)

_LIVE_TASK: tuple[T, ...] = (
    T.PENDING,
    T.READY,
    T.IN_PROGRESS,
    T.TOURNAMENT,
    T.SUBMITTED,
    T.TESTING,
    T.REWORK,
    T.BLOCKED,
    T.ESCALATED,
)

TASK_TRANSITIONS: dict[T, frozenset[T]] = {
    T.PENDING: frozenset({T.READY}),
    T.READY: frozenset({T.IN_PROGRESS, T.TOURNAMENT}),
    T.IN_PROGRESS: frozenset({T.SUBMITTED, T.BLOCKED, T.ESCALATED}),
    T.TOURNAMENT: frozenset({T.SUBMITTED, T.BLOCKED, T.ESCALATED}),
    T.SUBMITTED: frozenset({T.TESTING}),
    T.TESTING: frozenset({T.DONE, T.REWORK}),
    T.REWORK: frozenset({T.IN_PROGRESS, T.TOURNAMENT, T.ESCALATED, T.BLOCKED}),
    T.BLOCKED: frozenset({T.READY, T.REWORK, T.ESCALATED}),
    T.ESCALATED: frozenset({T.REWORK}),
    T.DONE: frozenset({T.REWORK}),
    T.CANCELLED: frozenset(),
}
# A REPLAN may cancel any task that is not terminal (DONE tasks are kept by the projector).
for _t in _LIVE_TASK:
    TASK_TRANSITIONS[_t] = TASK_TRANSITIONS[_t] | {T.CANCELLED}


def mission_transition_ok(frm: M, to: M) -> bool:
    """True if ``frm -> to`` is in the mission table."""
    return to in MISSION_TRANSITIONS.get(frm, frozenset())


def task_transition_ok(frm: T, to: T) -> bool:
    """True if ``frm -> to`` is in the task table."""
    return to in TASK_TRANSITIONS.get(frm, frozenset())


def assert_legal(frm: M | T, to: M | T) -> None:
    """Raise ``IllegalTransition`` unless ``frm -> to`` is legal (mission or task statuses)."""
    if isinstance(frm, M) and isinstance(to, M):
        ok = mission_transition_ok(frm, to)
    elif isinstance(frm, T) and isinstance(to, T):
        ok = task_transition_ok(frm, to)
    else:
        raise IllegalTransition(f"cannot transition between different kinds: {frm!r} -> {to!r}")
    if not ok:
        raise IllegalTransition(f"illegal transition {frm.value} -> {to.value}")
