"""Projector: one test per stateful event type, plus malformed-payload and completeness checks."""

from __future__ import annotations

from typing import Any

import pytest
from factories import (
    make_event,
    make_evidence,
    make_finding,
    make_mission,
    make_plan_record,
    make_scored_verdict,
    make_spec,
    make_submission,
    make_task,
    make_test_run,
)
from pydantic_core import to_jsonable_python

from devpilot.core.events import EPHEMERAL, Event, EventType
from devpilot.core.models import (
    ACStatus,
    Action,
    AgentMessage,
    Attempt,
    HumanDecision,
    HumanPrompt,
    LLMUsage,
    MessageType,
    Mission,
    MissionStatus,
    PreMortem,
    TaskStatus,
    WatchCondition,
)
from devpilot.state import projector
from devpilot.state.projector import ProjectionError, apply


def ev(type_: EventType, payload: dict[str, Any], seq: int = 1) -> Event:
    return make_event(type_, to_jsonable_python(payload), seq=seq)


def seeded() -> Mission:
    """A mission with a spec, ACs and two tasks, as it would look mid-run."""
    m = make_mission()
    sub = make_submission("MissionSpec", make_spec("AC-1", "AC-2").model_dump(mode="json"))
    apply(m, ev(EventType.SUBMISSION, {"submission": sub}))
    rec = make_plan_record(1, "T1", "T2")
    tasks = {"T1": make_task("T1"), "T2": make_task("T2")}
    apply(m, ev(EventType.PLAN_ADOPTED, {"plan_record": rec, "tasks": tasks}, seq=2))
    return m


def test_every_event_type_has_handler() -> None:
    assert set(projector.HANDLERS) == set(EventType)


def test_mission_created_replaces_fields_keeping_identity() -> None:
    m = make_mission("blank")
    ident = id(m)
    src = make_mission("M-9")
    src.request = "other"
    apply(m, ev(EventType.MISSION_CREATED, {"mission": src}, seq=1))
    assert id(m) == ident
    assert (m.id, m.request, m.last_seq) == ("M-9", "other", 1)


def test_state_changed_terminal_sets_reason() -> None:
    m = make_mission()
    apply(m, ev(EventType.STATE_CHANGED, {"from": "CREATED", "to": MissionStatus.PLANNING, "reason": "go"}))
    assert m.status == MissionStatus.PLANNING and m.outcome_reason is None
    apply(
        m, ev(EventType.STATE_CHANGED, {"from": "PLANNING", "to": MissionStatus.FAILED, "reason": "boom"}, 2)
    )
    assert m.status == MissionStatus.FAILED and m.outcome_reason == "boom"


def test_intel_ready() -> None:
    from devpilot.core.models import RepoIntel

    intel = RepoIntel(
        languages={"python": 3},
        file_count=3,
        test_framework="pytest",
        test_command=["pytest"],
        repo_map=[],
        conventions=[],
        risks=[],
    )
    m = make_mission()
    apply(m, ev(EventType.INTEL_READY, {"intel": intel}))
    assert m.intel == intel


def test_submission_repo_brief_sets_brief() -> None:
    from devpilot.core.models import RepoBrief

    brief = RepoBrief(
        summary="s", relevant_files=[], conventions_confirmed=[], risks=[], baseline_summary="b"
    )
    m = make_mission()
    sub = make_submission("RepoBrief", brief.model_dump(mode="json"), "S-b")
    apply(m, ev(EventType.SUBMISSION, {"submission": sub}))
    assert m.brief == brief and "S-b" in m.submissions


def test_submission_spec_builds_acs() -> None:
    m = seeded()
    assert m.spec is not None
    assert [a.ac.id for a in m.acs] == ["AC-1", "AC-2"]
    assert all(a.status == ACStatus.PENDING for a in m.acs)


def test_spec_resubmission_preserves_ac_state() -> None:
    m = seeded()
    apply(
        m,
        ev(
            EventType.AC_STATUS_CHANGED,
            {"ac_id": "AC-1", "status": ACStatus.VERIFIED, "evidence_ids": ["E-0001"], "confidence": 0.8},
            3,
        ),
    )
    sub = make_submission("MissionSpec", make_spec("AC-1", "AC-3").model_dump(mode="json"), "S-2")
    apply(m, ev(EventType.SUBMISSION, {"submission": sub}, 4))
    by_id = {a.ac.id: a for a in m.acs}
    assert list(by_id) == ["AC-1", "AC-3"]
    assert by_id["AC-1"].status == ACStatus.VERIFIED
    assert by_id["AC-1"].evidence_ids == ["E-0001"] and by_id["AC-1"].confidence == 0.8
    assert by_id["AC-3"].status == ACStatus.PENDING


def test_plan_adopted_cancels_dropped_tasks_but_not_done() -> None:
    m = seeded()
    m.tasks["T2"].status = TaskStatus.DONE
    m.tasks["T1"].status = TaskStatus.IN_PROGRESS
    wc = WatchCondition(description="d", trigger="test_fails", pattern="*", response=Action.REPLAN)
    rec = make_plan_record(2, "T3")
    rec.premortem = PreMortem(risks=[], watch_conditions=[wc])
    apply(m, ev(EventType.PLAN_ADOPTED, {"plan_record": rec, "tasks": {"T3": make_task("T3")}}, 3))
    assert m.tasks["T1"].status == TaskStatus.CANCELLED
    assert m.tasks["T2"].status == TaskStatus.DONE
    assert "T3" in m.tasks and len(m.plans) == 2
    assert m.watch_conditions == [wc]


def test_task_state_changed_attempt_upsert_and_inbox() -> None:
    m = seeded()
    m.tasks["T1"].inbox = ["MSG-1", "MSG-2"]
    a1 = Attempt(n=1, mode_id="samurai.implement", agent_id="samurai#1", model="m")
    apply(
        m,
        ev(
            EventType.TASK_STATE_CHANGED,
            {
                "task_key": "T1",
                "to": TaskStatus.IN_PROGRESS,
                "assignee": "samurai#1",
                "attempt": a1,
                "inbox_consumed": ["MSG-1"],
            },
            3,
        ),
    )
    t = m.tasks["T1"]
    assert (t.status, t.assignee, t.inbox) == (TaskStatus.IN_PROGRESS, "samurai#1", ["MSG-2"])
    a1b = a1.model_copy(update={"outcome": "green"})
    apply(m, ev(EventType.TASK_STATE_CHANGED, {"task_key": "T1", "to": TaskStatus.DONE, "attempt": a1b}, 4))
    assert len(t.attempts) == 1 and t.attempts[0].outcome == "green" and t.assignee == "samurai#1"
    with pytest.raises(ProjectionError):
        apply(m, ev(EventType.TASK_STATE_CHANGED, {"task_key": "T9", "to": TaskStatus.DONE}, 5))


def test_llm_turn_accumulates_budget() -> None:
    m = make_mission()
    u = LLMUsage(
        model="m",
        tokens_in=10,
        tokens_out=5,
        tokens_cached_read=3,
        tokens_thinking=2,
        cost_usd=0.25,
        latency_ms=1,
    )
    apply(m, ev(EventType.LLM_TURN, {"usage": u}))
    apply(m, ev(EventType.LLM_TURN, {"usage": u}, 2))
    b = m.budget
    assert (b.tokens_in, b.tokens_out, b.tokens_cached, b.tokens_thinking, b.cost_usd) == (20, 10, 6, 4, 0.5)


def test_budget_warning_applies_absolute_counters_and_ignores_unknown() -> None:
    m = make_mission()
    payload = {"fix_cycles": 2, "replans": 1, "tournaments": 1, "wall_clock_s": 12.5, "x": 9}
    apply(m, ev(EventType.BUDGET_WARNING, payload))
    b = m.budget
    assert (b.fix_cycles, b.replans, b.tournaments, b.wall_clock_s) == (2, 1, 1, 12.5)
    apply(m, ev(EventType.BUDGET_WARNING, {"fix_cycles": 3, "max_fix_cycles": 8}, 2))
    assert (m.budget.fix_cycles, m.budget.tournaments) == (3, 1)  # absolute; untouched keys kept
    apply(m, ev(EventType.BUDGET_WARNING, {"note": "nothing"}, 3))
    assert m.budget.fix_cycles == 3


@pytest.mark.parametrize(
    "payload",
    [{"fix_cycles": "2"}, {"fix_cycles": 1.5}, {"fix_cycles": True}, {"wall_clock_s": -1}, {"replans": None}],
)
def test_budget_warning_rejects_bad_values(payload: dict[str, Any]) -> None:
    m = make_mission()
    with pytest.raises(ProjectionError):
        apply(m, ev(EventType.BUDGET_WARNING, payload))
    assert m.budget.fix_cycles == 0


def test_tool_call_counts() -> None:
    m = make_mission()
    apply(m, ev(EventType.TOOL_CALL, {"anything": 1}))
    apply(m, ev(EventType.TOOL_CALL, {}, 2))
    assert m.budget.tool_calls == 2


def test_tool_result_records_evidence_when_present() -> None:
    m = make_mission()
    apply(m, ev(EventType.TOOL_RESULT, {"ok": True}))
    assert m.evidence == {}
    apply(m, ev(EventType.TOOL_RESULT, {"evidence": make_evidence("E-0007")}, 2))
    assert "E-0007" in m.evidence


def test_test_run_appends_run_and_evidence() -> None:
    m = make_mission()
    apply(m, ev(EventType.TEST_RUN, {"test_run": make_test_run(), "evidence": make_evidence("E-0002")}))
    assert len(m.test_runs) == 1 and "E-0002" in m.evidence


def test_verdict_appended() -> None:
    m = make_mission()
    apply(m, ev(EventType.VERDICT, {"verdict": make_scored_verdict()}))
    assert m.verdicts[0].id == "V-1"


def test_ac_status_changed_and_unknown() -> None:
    m = seeded()
    apply(
        m,
        ev(
            EventType.AC_STATUS_CHANGED,
            {"ac_id": "AC-2", "status": ACStatus.FAILED, "evidence_ids": ["E-1"]},
            3,
        ),
    )
    ac = m.acs[1]
    assert (ac.status, ac.evidence_ids, ac.confidence) == (ACStatus.FAILED, ["E-1"], None)
    with pytest.raises(ProjectionError):
        apply(
            m,
            ev(
                EventType.AC_STATUS_CHANGED,
                {"ac_id": "AC-9", "status": ACStatus.FAILED, "evidence_ids": []},
                4,
            ),
        )


def test_finding_upsert() -> None:
    m = make_mission()
    f = make_finding()
    apply(m, ev(EventType.FINDING, {"finding": f}))
    f2 = f.model_copy(update={"status": "addressed"})
    apply(m, ev(EventType.FINDING, {"finding": f2}, 2))
    assert len(m.findings) == 1 and m.findings["F-1"].status == "addressed"


def test_message_sent_routes_to_task_inbox() -> None:
    m = seeded()

    def msg(mid: str, to: str) -> AgentMessage:
        return AgentMessage(id=mid, sender="master", to=to, type=MessageType.INFO, subject="s", body="b")

    apply(m, ev(EventType.MESSAGE_SENT, {"message": msg("MSG-1", "task:T1")}, 3))
    apply(m, ev(EventType.MESSAGE_SENT, {"message": msg("MSG-2", "task:T404")}, 4))
    apply(m, ev(EventType.MESSAGE_SENT, {"message": msg("MSG-3", "human")}, 5))
    assert set(m.messages) == {"MSG-1", "MSG-2", "MSG-3"}
    assert m.tasks["T1"].inbox == ["MSG-1"] and m.tasks["T2"].inbox == []


def test_decision_appends_submission() -> None:
    m = seeded()
    apply(m, ev(EventType.SUBMISSION, {"submission": make_submission("Decision", {"x": 1}, "S-d")}, 3))
    apply(m, ev(EventType.DECISION, {"submission_id": "S-d", "final_action": Action.CONTINUE}, 4))
    assert [d.id for d in m.decisions] == ["S-d"]
    with pytest.raises(ProjectionError):
        apply(m, ev(EventType.DECISION, {"submission_id": "nope", "final_action": Action.CONTINUE}, 5))


def test_checkpoint_records_seq() -> None:
    m = make_mission()
    apply(
        m, ev(EventType.CHECKPOINT, {"sha": "abc", "label": "after T1", "progress": {"failing_public": 1}}, 7)
    )
    assert m.checkpoints == [{"sha": "abc", "seq": 7, "label": "after T1", "progress": {"failing_public": 1}}]


def test_human_prompt_and_decision() -> None:
    m = make_mission()
    p = HumanPrompt(id="P-1", gate="plan", title="t", body_md="b")
    apply(m, ev(EventType.HUMAN_PROMPT, {"prompt": p}))
    assert m.prompts["P-1"].status == "open"
    d = HumanDecision(id="HD-1", prompt_id="P-1", choice="approve")
    apply(m, ev(EventType.HUMAN_DECISION, {"decision": d}, 2))
    assert m.prompts["P-1"].status == "answered" and m.human_decisions[0].choice == "approve"
    bad = HumanDecision(id="HD-2", prompt_id="P-404")
    with pytest.raises(ProjectionError):
        apply(m, ev(EventType.HUMAN_DECISION, {"decision": bad}, 3))


@pytest.mark.parametrize("type_", [t for t in EventType if t not in projector._STATEFUL])
def test_informational_events_only_advance_last_seq(type_: EventType) -> None:
    m = make_mission()
    before = m.model_dump()
    apply(m, ev(type_, {"whatever": 1}, 5))
    after = m.model_dump()
    if type_ in EPHEMERAL:
        assert after == before
    else:
        assert after.pop("last_seq") == 5
        before.pop("last_seq")
        assert after == before


def test_malformed_payload_raises_projection_error() -> None:
    m = make_mission()
    with pytest.raises(ProjectionError):
        apply(m, ev(EventType.LLM_TURN, {"usage": {"bogus": 1}}))
    with pytest.raises(ProjectionError):
        apply(m, ev(EventType.FINDING, {}))
    with pytest.raises(ProjectionError):
        apply(m, ev(EventType.STATE_CHANGED, {"to": "NOT_A_STATUS", "from": "x", "reason": ""}))
