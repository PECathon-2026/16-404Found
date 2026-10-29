"""Canonical enumerations. Single source of truth: AGENTS.md §0.3 (parity is tested)."""
from __future__ import annotations

from enum import StrEnum


class MissionStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class TaskKind(StrEnum):
    RECON = "RECON"
    IMPLEMENT = "IMPLEMENT"
    WRITE_TESTS = "WRITE_TESTS"
    RUN_CHECKS = "RUN_CHECKS"
    REPAIR = "REPAIR"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    VERIFY = "VERIFY"


class MasterAction(StrEnum):
    PLAN = "PLAN"
    DELEGATE = "DELEGATE"
    EXECUTE = "EXECUTE"
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    VERIFY = "VERIFY"
    ESCALATE = "ESCALATE"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return list(Severity).index(self)


class MessageType(StrEnum):
    TASK_ASSIGN = "TASK_ASSIGN"
    TASK_ACK = "TASK_ACK"
    TASK_RESULT = "TASK_RESULT"
    FINDING = "FINDING"
    CRITIQUE = "CRITIQUE"
    CRITIQUE_RESPONSE = "CRITIQUE_RESPONSE"
    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    REPLAN_REQUEST = "REPLAN_REQUEST"
    ESCALATION = "ESCALATION"
    DECISION = "DECISION"
    STATUS = "STATUS"
    HEARTBEAT = "HEARTBEAT"


class CriterionStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    FIX_PROPOSED = "FIX_PROPOSED"
    RESOLVED = "RESOLVED"
    DISPUTED = "DISPUTED"
    WAIVED_BY_HUMAN = "WAIVED_BY_HUMAN"
    WONT_FIX_EVIDENCED = "WONT_FIX_EVIDENCED"


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class FailureClass(StrEnum):
    ASSERTION = "ASSERTION"
    IMPORT_ERROR = "IMPORT_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    TIMEOUT = "TIMEOUT"
    ENV_MISSING_TOOL = "ENV_MISSING_TOOL"
    DEPENDENCY = "DEPENDENCY"
    FLAKY = "FLAKY"
    LINT = "LINT"
    BUILD = "BUILD"
    UNKNOWN = "UNKNOWN"


class AgentId(StrEnum):
    MASTER = "master"
    PLANNER = "planner"
    DEVELOPER = "developer"
    TESTER = "tester"
    SECURITY = "security"
    VERIFIER = "verifier"
    SYSTEM = "system"
    HUMAN = "human"


TERMINAL_STATUSES = frozenset(
    {MissionStatus.COMPLETED, MissionStatus.REJECTED, MissionStatus.FAILED, MissionStatus.CANCELLED}
)

EVENT_TYPES = (
    "mission.created mission.status_changed mission.completed mission.failed "
    "agent.started agent.finished task.created task.delegated task.status_changed task.superseded "
    "decision.made message.sent critique.raised critique.resolved tool.called tool.completed tool.failed "
    "file.modified test.run_started test.passed test.failed repair.initiated finding.created finding.resolved "
    "verification.started verification.completed approval.requested approval.resolved budget.warning "
    "human.input_requested human.input_received policy.denied"
).split()
