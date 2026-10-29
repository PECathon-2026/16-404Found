"""Pure event -> Mission reducer.

``apply`` mutates a ``Mission`` in place from one persisted ``Event``. It is deterministic and
does no I/O, so replaying the same events always yields the same aggregate (resume, time travel,
and the live blackboard all share this one code path).

Every ``EventType`` must have a handler; informational events register ``_noop`` explicitly so a
newly added event type fails at import time instead of being silently ignored.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from devpilot.core.events import EPHEMERAL, Event, EventType
from devpilot.core.models import (
    ACState,
    ACStatus,
    Action,
    AgentMessage,
    Attempt,
    Evidence,
    Finding,
    HumanDecision,
    HumanPrompt,
    LLMUsage,
    Mission,
    MissionSpec,
    MissionStatus,
    PlanRecord,
    RepoBrief,
    RepoIntel,
    ScoredVerdict,
    Submission,
    Task,
    TaskStatus,
    TestRun,
)


class ProjectionError(Exception):
    """An event payload does not satisfy its contract or references unknown state."""


Handler = Callable[[Mission, Event], None]


def _noop(mission: Mission, event: Event) -> None:
    """Informational events: recorded in the log, no aggregate change."""


def _get(event: Event, key: str) -> Any:
    try:
        return event.payload[key]
    except KeyError:
        raise ProjectionError(f"{event.type} seq={event.seq}: missing payload key {key!r}") from None


def _created(mission: Mission, event: Event) -> None:
    new = Mission.model_validate(_get(event, "mission"))
    # Same object identity: callers hold references to the live mission.
    for name in Mission.model_fields:
        setattr(mission, name, getattr(new, name))


def _state_changed(mission: Mission, event: Event) -> None:
    to = MissionStatus(_get(event, "to"))
    reason = str(event.payload.get("reason", ""))
    mission.status = to
    if to.terminal:
        mission.outcome_reason = reason


def _intel_ready(mission: Mission, event: Event) -> None:
    mission.intel = RepoIntel.model_validate(_get(event, "intel"))


def _submission(mission: Mission, event: Event) -> None:
    sub = Submission.model_validate(_get(event, "submission"))
    mission.submissions[sub.id] = sub
    if sub.output_type == "RepoBrief":
        mission.brief = RepoBrief.model_validate(sub.payload)
    elif sub.output_type == "MissionSpec":
        spec = MissionSpec.model_validate(sub.payload)
        existing = {a.ac.id: a for a in mission.acs}
        mission.spec = spec
        acs: list[ACState] = []
        for crit in spec.acceptance_criteria:
            old = existing.get(crit.id)
            if old is None:
                acs.append(ACState(ac=crit))
            else:
                acs.append(
                    ACState(
                        ac=crit, status=old.status, evidence_ids=old.evidence_ids, confidence=old.confidence
                    )
                )
        mission.acs = acs


def _plan_adopted(mission: Mission, event: Event) -> None:
    record = PlanRecord.model_validate(_get(event, "plan_record"))
    raw_tasks = _get(event, "tasks")
    tasks = {key: Task.model_validate(t) for key, t in raw_tasks.items()}
    mission.plans.append(record)
    for key, old in mission.tasks.items():
        if key not in tasks and old.status != TaskStatus.DONE:
            old.status = TaskStatus.CANCELLED
    mission.tasks.update(tasks)
    if record.premortem is not None and record.premortem.watch_conditions:
        mission.watch_conditions = list(record.premortem.watch_conditions)


def _task_state_changed(mission: Mission, event: Event) -> None:
    key = _get(event, "task_key")
    task = mission.tasks.get(key)
    if task is None:
        raise ProjectionError(f"TASK_STATE_CHANGED seq={event.seq}: unknown task {key!r}")
    status = TaskStatus(_get(event, "to"))
    attempt = Attempt.model_validate(event.payload["attempt"]) if "attempt" in event.payload else None
    task.status = status
    if "assignee" in event.payload:
        task.assignee = event.payload["assignee"]
    if attempt is not None:
        for i, existing in enumerate(task.attempts):
            if existing.n == attempt.n:
                task.attempts[i] = attempt
                break
        else:
            task.attempts.append(attempt)
    consumed = set(event.payload.get("inbox_consumed") or [])
    if consumed:
        task.inbox = [m for m in task.inbox if m not in consumed]


def _llm_turn(mission: Mission, event: Event) -> None:
    usage = LLMUsage.model_validate(_get(event, "usage"))
    b = mission.budget
    b.tokens_in += usage.tokens_in
    b.tokens_out += usage.tokens_out
    b.tokens_cached += usage.tokens_cached_read
    b.tokens_thinking += usage.tokens_thinking
    b.cost_usd += usage.cost_usd


def _tool_call(mission: Mission, event: Event) -> None:
    mission.budget.tool_calls += 1


def _record_evidence(mission: Mission, event: Event) -> None:
    raw = event.payload.get("evidence")
    if raw is not None:
        ev = Evidence.model_validate(raw)
        mission.evidence[ev.id] = ev


def _test_run(mission: Mission, event: Event) -> None:
    run = TestRun.model_validate(_get(event, "test_run"))
    _record_evidence(mission, event)
    mission.test_runs.append(run)


def _verdict(mission: Mission, event: Event) -> None:
    mission.verdicts.append(ScoredVerdict.model_validate(_get(event, "verdict")))


def _ac_status_changed(mission: Mission, event: Event) -> None:
    ac_id = _get(event, "ac_id")
    state = next((a for a in mission.acs if a.ac.id == ac_id), None)
    if state is None:
        raise ProjectionError(f"AC_STATUS_CHANGED seq={event.seq}: unknown AC {ac_id!r}")
    state.status = ACStatus(_get(event, "status"))
    state.evidence_ids = list(_get(event, "evidence_ids"))
    if "confidence" in event.payload:
        state.confidence = event.payload["confidence"]


def _finding(mission: Mission, event: Event) -> None:
    f = Finding.model_validate(_get(event, "finding"))
    mission.findings[f.id] = f


def _message_sent(mission: Mission, event: Event) -> None:
    msg = AgentMessage.model_validate(_get(event, "message"))
    mission.messages[msg.id] = msg
    if msg.to.startswith("task:"):
        task = mission.tasks.get(msg.to.removeprefix("task:"))
        if task is not None and msg.id not in task.inbox:
            task.inbox.append(msg.id)


def _decision(mission: Mission, event: Event) -> None:
    sid = _get(event, "submission_id")
    sub = mission.submissions.get(sid)
    if sub is None:
        raise ProjectionError(f"DECISION seq={event.seq}: unknown submission {sid!r}")
    Action(_get(event, "final_action"))  # validate the contract even though it is not stored
    mission.decisions.append(sub.model_copy(deep=True))


def _checkpoint(mission: Mission, event: Event) -> None:
    mission.checkpoints.append(
        {
            "sha": _get(event, "sha"),
            "seq": event.seq,
            "label": _get(event, "label"),
            "progress": event.payload.get("progress"),
        }
    )


def _human_prompt(mission: Mission, event: Event) -> None:
    p = HumanPrompt.model_validate(_get(event, "prompt"))
    mission.prompts[p.id] = p


def _human_decision(mission: Mission, event: Event) -> None:
    d = HumanDecision.model_validate(_get(event, "decision"))
    prompt = mission.prompts.get(d.prompt_id)
    if prompt is None:
        raise ProjectionError(f"HUMAN_DECISION seq={event.seq}: unknown prompt {d.prompt_id!r}")
    mission.human_decisions.append(d)
    prompt.status = "answered"


_STATEFUL: dict[EventType, Handler] = {
    EventType.MISSION_CREATED: _created,
    EventType.STATE_CHANGED: _state_changed,
    EventType.INTEL_READY: _intel_ready,
    EventType.SUBMISSION: _submission,
    EventType.PLAN_ADOPTED: _plan_adopted,
    EventType.TASK_STATE_CHANGED: _task_state_changed,
    EventType.LLM_TURN: _llm_turn,
    EventType.TOOL_CALL: _tool_call,
    EventType.TOOL_RESULT: _record_evidence,
    EventType.TEST_RUN: _test_run,
    EventType.VERDICT: _verdict,
    EventType.AC_STATUS_CHANGED: _ac_status_changed,
    EventType.FINDING: _finding,
    EventType.MESSAGE_SENT: _message_sent,
    EventType.DECISION: _decision,
    EventType.CHECKPOINT: _checkpoint,
    EventType.HUMAN_PROMPT: _human_prompt,
    EventType.HUMAN_DECISION: _human_decision,
}

_INFORMATIONAL: tuple[EventType, ...] = (
    EventType.MISSION_FINISHED,
    EventType.WATCH_TRIGGERED,
    EventType.AGENT_SPAWNED,
    EventType.MODE_STARTED,
    EventType.MODE_FINISHED,
    EventType.MODE_FAILED,
    EventType.AGENT_TEXT_DELTA,
    EventType.MODEL_ESCALATED,
    EventType.POLICY_DENIED,
    EventType.TOOL_UNAVAILABLE,
    EventType.CIRCUIT_OPENED,
    EventType.DELTA_DEBUG,
    EventType.GUARD_OVERRIDE,
    EventType.STRATEGY_CHANGED,
    EventType.DISPUTE_OPENED,
    EventType.DISPUTE_RESOLVED,
    EventType.TOURNAMENT_STARTED,
    EventType.TOURNAMENT_SCORED,
    EventType.TOURNAMENT_DECIDED,
    EventType.ROLLBACK,
    EventType.APPLIED,
    EventType.BUDGET_WARNING,
    EventType.BUDGET_EXCEEDED,
    EventType.MEMORY_RECALLED,
    EventType.MEMORY_WRITTEN,
    EventType.REPORT_WRITTEN,
)

HANDLERS: dict[EventType, Handler] = {**_STATEFUL, **dict.fromkeys(_INFORMATIONAL, _noop)}

assert set(HANDLERS) == set(EventType), (
    f"projector has no handler for: {sorted(set(EventType) - set(HANDLERS))}"
)
assert len(_STATEFUL) + len(_INFORMATIONAL) == len(HANDLERS), "event type registered twice"


def apply(mission: Mission, event: Event) -> None:
    """Fold one event into ``mission``. Ephemeral events never change the aggregate."""
    if event.type in EPHEMERAL:
        return
    try:
        HANDLERS[event.type](mission, event)
    except ProjectionError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ProjectionError(f"{event.type} seq={event.seq}: malformed payload: {exc}") from exc
    mission.last_seq = event.seq
