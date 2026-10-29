"""Tests for core/state.py, core/logger.py, core/board.py."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure devpilot root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state import (
    SharedState,
    Criterion,
    CriterionStatus,
    Task,
    TaskStatus,
    Attempt,
    Message,
    TestRun,
    ReviewIssue,
    RunStatus,
)
from core.logger import RunLogger, RUNS_DIR
from core.board import MessageBoard


# ---------- State tests ----------


def test_shared_state_defaults():
    """SharedState has sensible defaults."""
    state = SharedState(
        run_id="test-001",
        request="add coupon",
        repo_path="/tmp/repo",
        workspace_path="/tmp/ws",
    )
    assert state.status == RunStatus.PLANNING
    assert state.retries == 0
    assert state.max_retries == 3
    assert state.criteria == []
    assert state.tasks == []


def test_criterion_status_transitions():
    """Criterion status can be updated."""
    c = Criterion(id="c1", text="cart should total correctly")
    assert c.status == CriterionStatus.UNMET
    c.status = CriterionStatus.MET
    c.evidence = "pytest passed"
    assert c.status == CriterionStatus.MET
    assert c.evidence == "pytest passed"


def test_task_lifecycle():
    """Task moves through status values."""
    t = Task(id="t1", text="implement coupon", owner="developer")
    assert t.status == TaskStatus.PENDING
    t.status = TaskStatus.IN_PROGRESS
    assert t.status == TaskStatus.IN_PROGRESS


def test_attempt_record():
    """Attempt stores agent, what, result."""
    a = Attempt(agent="developer", what_was_tried="used round()", result="failed rounding test")
    assert a.agent == "developer"
    assert "round()" in a.what_was_tried


# ---------- Logger tests ----------


def test_logger_writes_jsonl(tmp_path, monkeypatch):
    """Logger creates a valid JSONL file."""
    monkeypatch.setattr("core.logger.RUNS_DIR", tmp_path)
    logger = RunLogger.__new__(RunLogger)
    logger.run_id = "r001"
    logger.path = tmp_path / "r001.jsonl"

    logger.log(agent="orchestrator", event_type="RUN_START", input_summary="test run")
    logger.log(agent="planner", event_type="PLAN_READY", tool="read_file")

    records = logger.read_all()
    assert len(records) == 2
    assert records[0]["agent"] == "orchestrator"
    assert records[0]["event_type"] == "RUN_START"
    assert records[1]["agent"] == "planner"


def test_logger_jsonl_valid_format(tmp_path, monkeypatch):
    """Each line is parseable JSON."""
    monkeypatch.setattr("core.logger.RUNS_DIR", tmp_path)
    logger = RunLogger.__new__(RunLogger)
    logger.run_id = "r002"
    logger.path = tmp_path / "r002.jsonl"

    logger.log("developer", "TOOL_CALL", tool="edit_file", output_summary="ok")

    with open(logger.path) as f:
        lines = f.readlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert "time" in record
    assert record["tool"] == "edit_file"


def test_logger_read_empty(tmp_path, monkeypatch):
    """Reading nonexistent log returns empty list."""
    monkeypatch.setattr("core.logger.RUNS_DIR", tmp_path)
    logger = RunLogger.__new__(RunLogger)
    logger.run_id = "r_none"
    logger.path = tmp_path / "r_none.jsonl"
    assert logger.read_all() == []


# ---------- MessageBoard tests ----------


def test_board_post_and_read():
    """Posted message is readable by its receiver."""
    board = MessageBoard()
    msg = board.post("PLAN_READY", sender="planner", receiver="developer", payload={"tasks": []})
    assert msg.type == "PLAN_READY"
    msgs = board.read_for("developer")
    assert len(msgs) == 1
    assert msgs[0].type == "PLAN_READY"


def test_board_read_for_filters():
    """read_for only returns messages for that agent."""
    board = MessageBoard()
    board.post("TEST_FAILURE", "verifier", "developer", {"error": "assertion failed"})
    board.post("PLAN_READY", "planner", "reviewer", {"plan": []})
    dev_msgs = board.read_for("developer")
    rev_msgs = board.read_for("reviewer")
    assert len(dev_msgs) == 1
    assert len(rev_msgs) == 1
    assert dev_msgs[0].type == "TEST_FAILURE"


def test_board_invalid_type_raises():
    """Posting an unknown message type raises ValueError."""
    board = MessageBoard()
    with pytest.raises(ValueError):
        board.post("MADE_UP_TYPE", "agent_a", "agent_b", {})


def test_board_has_type():
    """has_type correctly detects presence of a message type."""
    board = MessageBoard()
    board.post("ESCALATE", "orchestrator", "human", {"reason": "stuck"})
    assert board.has_type("ESCALATE")
    assert not board.has_type("CLARIFY")


def test_board_message_has_id():
    """Every posted message gets a unique short id."""
    board = MessageBoard()
    m1 = board.post("CLARIFY", "planner", "human", {})
    m2 = board.post("CLARIFY", "planner", "human", {})
    assert m1.id != m2.id
