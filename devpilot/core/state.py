"""Shared state dataclasses for DevPilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    """Overall run lifecycle status."""

    PLANNING = "planning"
    BUILDING = "building"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    AWAITING_HUMAN = "awaiting_human"
    DONE = "done"
    ESCALATED = "escalated"
    STOPPED = "stopped"


class CriterionStatus(str, Enum):
    """Status of a single acceptance criterion."""

    UNMET = "unmet"
    MET = "met"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """Status of a single task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass
class Criterion:
    """One acceptance criterion with id, text, and status tracking."""

    id: str
    text: str
    status: CriterionStatus = CriterionStatus.UNMET
    evidence: str = ""


@dataclass
class Task:
    """A unit of work assigned to an agent."""

    id: str
    text: str
    owner: str  # "developer" | "planner" | etc.
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class Attempt:
    """Record of a single fix attempt to prevent repetition."""

    agent: str
    what_was_tried: str
    result: str


@dataclass
class Message:
    """A typed message posted on the message board."""

    type: str  # e.g. PLAN_READY, TEST_FAILURE, ...
    sender: str
    receiver: str
    payload: dict[str, Any]
    id: str = ""


@dataclass
class RunTestRecord:
    """Result of a single test command execution."""

    command: str
    exit_code: int
    output: str
    timestamp: str


# Backward-compatible alias
TestRun = RunTestRecord


@dataclass
class ReviewIssue:
    """A code-review issue posted by the Reviewer agent."""

    id: str
    severity: str  # "low" | "medium" | "high" | "critical"
    file: str
    line: int
    text: str
    status: str = "open"  # "open" | "resolved" | "disputed"


@dataclass
class SharedState:
    """The full shared state for one DevPilot run."""

    run_id: str
    request: str
    repo_path: str
    workspace_path: str
    criteria: list[Criterion] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    test_runs: list[TestRun] = field(default_factory=list)
    review_issues: list[ReviewIssue] = field(default_factory=list)
    retries: int = 0
    max_retries: int = 3
    status: RunStatus = RunStatus.PLANNING
    simulate_missing: str | None = None
    steps_per_agent: dict[str, int] = field(default_factory=dict)
    max_steps_per_agent: int = 15
    last_edit_time: str = ""
    last_verify_time: str = ""
