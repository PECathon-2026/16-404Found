"""Transition tables: every legal edge is accepted, everything else is rejected."""

from __future__ import annotations

import itertools

import pytest

from devpilot.core.models import MissionStatus as M
from devpilot.core.models import TaskStatus as T
from devpilot.orchestrator.transitions import (
    MISSION_TRANSITIONS,
    TASK_TRANSITIONS,
    IllegalTransition,
    assert_legal,
)

LEGAL_MISSION = [
    (M.CREATED, M.INTEL),
    (M.INTEL, M.RECON),
    (M.RECON, M.ANALYZING),
    (M.ANALYZING, M.CLARIFYING),
    (M.CLARIFYING, M.ANALYZING),
    (M.ANALYZING, M.PLANNING),
    (M.PLANNING, M.AWAITING_PLAN_APPROVAL),
    (M.AWAITING_PLAN_APPROVAL, M.PLANNING),
    (M.AWAITING_PLAN_APPROVAL, M.AUTHORING_ACCEPTANCE),
    (M.PLANNING, M.AUTHORING_ACCEPTANCE),
    (M.AUTHORING_ACCEPTANCE, M.EXECUTING),
    (M.EXECUTING, M.TESTING),
    (M.TESTING, M.DECIDING),
    (M.TESTING, M.CHECKING),
    (M.CHECKING, M.DECIDING),
    (M.CHECKING, M.AWAITING_APPLY),
    (M.CHECKING, M.CHECKING),
    (M.DECIDING, M.EXECUTING),
    (M.DECIDING, M.PLANNING),
    (M.AWAITING_APPLY, M.APPLYING),
    (M.AWAITING_APPLY, M.DECIDING),
    (M.AWAITING_APPLY, M.REPORTING),
    (M.APPLYING, M.REPORTING),
    (M.REPORTING, M.COMPLETED_VERIFIED),
    (M.REPORTING, M.COMPLETED_PARTIAL),
    (M.REPORTING, M.FAILED),
    (M.REPORTING, M.ABORTED),
]
ILLEGAL_MISSION = [
    (M.CREATED, M.EXECUTING),
    (M.RECON, M.PLANNING),
    (M.ANALYZING, M.EXECUTING),
    (M.PLANNING, M.TESTING),
    (M.EXECUTING, M.AWAITING_APPLY),
    (M.EXECUTING, M.APPLYING),
    (M.TESTING, M.AWAITING_APPLY),
    (M.CHECKING, M.APPLYING),
    (M.AWAITING_APPLY, M.EXECUTING),
    (M.APPLYING, M.DECIDING),
    (M.REPORTING, M.EXECUTING),
    (M.REPORTING, M.REPORTING),
    (M.EXECUTING, M.COMPLETED_VERIFIED),
    (M.AWAITING_APPLY, M.COMPLETED_VERIFIED),
    (M.TESTING, M.TESTING),
]


@pytest.mark.parametrize(("frm", "to"), LEGAL_MISSION)
def test_legal_mission_edges(frm: M, to: M) -> None:
    assert_legal(frm, to)


@pytest.mark.parametrize(("frm", "to"), ILLEGAL_MISSION)
def test_illegal_mission_edges(frm: M, to: M) -> None:
    with pytest.raises(IllegalTransition, match=f"{frm.value} -> {to.value}"):
        assert_legal(frm, to)


@pytest.mark.parametrize("frm", [s for s in M if not s.terminal])
def test_any_live_state_may_abort_or_report(frm: M) -> None:
    assert_legal(frm, M.ABORTED)
    if frm != M.REPORTING:
        assert_legal(frm, M.REPORTING)


@pytest.mark.parametrize(("frm", "to"), list(itertools.product([s for s in M if s.terminal], list(M))))
def test_terminal_states_have_no_exits(frm: M, to: M) -> None:
    assert MISSION_TRANSITIONS[frm] == frozenset()
    with pytest.raises(IllegalTransition):
        assert_legal(frm, to)


def test_every_mission_status_has_a_row() -> None:
    assert set(MISSION_TRANSITIONS) == set(M)
    assert set(TASK_TRANSITIONS) == set(T)


LEGAL_TASK = [
    (T.PENDING, T.READY),
    (T.READY, T.IN_PROGRESS),
    (T.IN_PROGRESS, T.SUBMITTED),
    (T.IN_PROGRESS, T.BLOCKED),
    (T.SUBMITTED, T.TESTING),
    (T.TESTING, T.DONE),
    (T.TESTING, T.REWORK),
    (T.REWORK, T.IN_PROGRESS),
    (T.REWORK, T.ESCALATED),
    (T.BLOCKED, T.READY),
    (T.BLOCKED, T.ESCALATED),
    (T.DONE, T.REWORK),
    (T.PENDING, T.CANCELLED),
    (T.REWORK, T.TOURNAMENT),
    (T.TOURNAMENT, T.SUBMITTED),
    (T.ESCALATED, T.REWORK),
    (T.BLOCKED, T.REWORK),
]
ILLEGAL_TASK = [
    (T.PENDING, T.IN_PROGRESS),
    (T.PENDING, T.DONE),
    (T.READY, T.DONE),
    (T.IN_PROGRESS, T.DONE),
    (T.SUBMITTED, T.DONE),
    (T.TESTING, T.IN_PROGRESS),
    (T.DONE, T.IN_PROGRESS),
    (T.DONE, T.CANCELLED),
    (T.CANCELLED, T.READY),
    (T.CANCELLED, T.CANCELLED),
    (T.ESCALATED, T.DONE),
    (T.REWORK, T.DONE),
    (T.DONE, T.DONE),
]


@pytest.mark.parametrize(("frm", "to"), LEGAL_TASK)
def test_legal_task_edges(frm: T, to: T) -> None:
    assert_legal(frm, to)


@pytest.mark.parametrize(("frm", "to"), ILLEGAL_TASK)
def test_illegal_task_edges(frm: T, to: T) -> None:
    with pytest.raises(IllegalTransition):
        assert_legal(frm, to)


def test_mixed_kinds_are_rejected() -> None:
    with pytest.raises(IllegalTransition, match="different kinds"):
        assert_legal(M.CREATED, T.READY)
