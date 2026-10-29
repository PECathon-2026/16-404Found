"""Event vocabulary. ``events.jsonl`` is the mission's source of truth; everything else
(blackboard, SQLite, UI) is a projection of it. The UI subscribes to this exact shape over
WebSocket, so treat ``Event`` as a public API.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from devpilot.core.models import Strict, utcnow


class EventType(StrEnum):
    # lifecycle
    MISSION_CREATED = "MISSION_CREATED"
    STATE_CHANGED = "STATE_CHANGED"
    MISSION_FINISHED = "MISSION_FINISHED"
    # intelligence / planning
    INTEL_READY = "INTEL_READY"
    SUBMISSION = "SUBMISSION"  # any validated LLMOutput (spec, plan, change report, verdict...)
    PLAN_ADOPTED = "PLAN_ADOPTED"
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"
    WATCH_TRIGGERED = "WATCH_TRIGGERED"
    # agents
    AGENT_SPAWNED = "AGENT_SPAWNED"
    MODE_STARTED = "MODE_STARTED"
    MODE_FINISHED = "MODE_FINISHED"
    MODE_FAILED = "MODE_FAILED"
    LLM_TURN = "LLM_TURN"  # usage + text/thinking summary of one model call
    AGENT_TEXT_DELTA = "AGENT_TEXT_DELTA"  # streaming tokens (UI only; not persisted)
    MODEL_ESCALATED = "MODEL_ESCALATED"
    # tools
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    POLICY_DENIED = "POLICY_DENIED"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    CIRCUIT_OPENED = "CIRCUIT_OPENED"
    # testing / verification
    TEST_RUN = "TEST_RUN"
    DELTA_DEBUG = "DELTA_DEBUG"
    VERDICT = "VERDICT"
    AC_STATUS_CHANGED = "AC_STATUS_CHANGED"
    # coordination
    FINDING = "FINDING"
    MESSAGE_SENT = "MESSAGE_SENT"
    DECISION = "DECISION"
    GUARD_OVERRIDE = "GUARD_OVERRIDE"
    STRATEGY_CHANGED = "STRATEGY_CHANGED"
    DISPUTE_OPENED = "DISPUTE_OPENED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    TOURNAMENT_STARTED = "TOURNAMENT_STARTED"
    TOURNAMENT_SCORED = "TOURNAMENT_SCORED"
    TOURNAMENT_DECIDED = "TOURNAMENT_DECIDED"
    # workspace
    CHECKPOINT = "CHECKPOINT"
    ROLLBACK = "ROLLBACK"
    APPLIED = "APPLIED"
    # human
    HUMAN_PROMPT = "HUMAN_PROMPT"
    HUMAN_DECISION = "HUMAN_DECISION"
    # budgets / memory / report
    BUDGET_WARNING = "BUDGET_WARNING"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    MEMORY_RECALLED = "MEMORY_RECALLED"
    MEMORY_WRITTEN = "MEMORY_WRITTEN"
    REPORT_WRITTEN = "REPORT_WRITTEN"


# Events not written to events.jsonl (high-volume, UI-only).
EPHEMERAL: frozenset[EventType] = frozenset({EventType.AGENT_TEXT_DELTA})


class Event(Strict):
    seq: int = Field(description="monotonic per mission; assigned by EventStore.append")
    mission_id: str
    type: EventType
    ts: datetime = Field(default_factory=utcnow)
    actor: str = Field(description="agent id ('samurai#2'), 'system' or 'human'")
    mode_id: str | None = None
    task_key: str | None = None
    span_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(default="", description="one human-readable line for timelines")
