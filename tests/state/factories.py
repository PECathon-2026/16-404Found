"""Factories for small, valid model instances used across the state tests (imported as ``factories``)."""

from __future__ import annotations

from typing import Any

from devpilot.core.events import Event, EventType
from devpilot.core.models import (
    AcceptanceCriterion,
    Ambiguity,
    Evidence,
    EvidenceKind,
    Finding,
    Level,
    Mission,
    MissionSpec,
    Plan,
    PlanRecord,
    ScoredVerdict,
    Severity,
    Submission,
    Task,
    TaskDraft,
    TestRun,
    VerificationMethod,
    VerifierVerdict,
)

MID = "M-1"


def make_mission(mid: str = MID) -> Mission:
    return Mission(id=mid, request="fix paging", repo_path="/repo", workspace_path="/ws")


def make_event(
    type_: EventType,
    payload: dict[str, Any] | None = None,
    *,
    mid: str = MID,
    seq: int = 0,
    actor: str = "system",
) -> Event:
    return Event(seq=seq, mission_id=mid, type=type_, actor=actor, payload=payload or {})


def make_ac(ac_id: str = "AC-1", preserve: bool = True) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=ac_id,
        given="a list",
        when="paged",
        then="page is returned",
        verification_methods=[VerificationMethod.EXISTING_TEST],
        preserves_existing_behaviour=preserve,
    )


def make_spec(*ac_ids: str) -> MissionSpec:
    ids = ac_ids or ("AC-1",)
    return MissionSpec(
        restated_request="fix paging",
        objectives=["o"],
        acceptance_criteria=[make_ac(i, preserve=(n == 0)) for n, i in enumerate(ids)],
        ambiguity=Ambiguity(level=Level.LOW),
        mission_kind="bugfix",
    )


def make_submission(output_type: str, payload: dict[str, Any], sid: str = "S-1") -> Submission:
    return Submission(
        id=sid,
        mode_id="shogun.analyze",
        agent_id="master",
        model="m",
        output_type=output_type,
        payload=payload,
    )


def make_task(key: str = "T1", status: str = "PENDING") -> Task:
    return Task(
        id=f"task-{key}",
        key=key,
        title="t",
        description="d",
        acceptance_refs=["AC-1"],
        files_to_touch=["a.py"],
        depends_on=[],
        may_edit_tests=False,
        risk=Level.LOW,
        plan_version=1,
        status=status,  # type: ignore[arg-type]
    )


def make_plan(*keys: str) -> Plan:
    return Plan(
        rationale="r",
        tasks=[
            TaskDraft(key=k, title="t", description="d", acceptance_refs=["AC-1"], files_to_touch=["a.py"])
            for k in keys or ("T1",)
        ],
    )


def make_plan_record(version: int = 1, *keys: str) -> PlanRecord:
    return PlanRecord(id=f"plan-{version}", version=version, plan=make_plan(*keys))


def make_evidence(eid: str = "E-0001") -> Evidence:
    return Evidence(
        id=eid,
        kind=EvidenceKind.TOOL_OUTPUT,
        tool="fs.read",
        agent_id="samurai#1",
        workspace_ref="main",
        workspace_sha="abc",
        summary="s",
        log_path="logs/x",
        sha256="0" * 64,
    )


def make_test_run(eid: str = "E-0002") -> TestRun:
    return TestRun(
        id="TR-1",
        evidence_id=eid,
        scope="full",
        workspace_ref="main",
        totals={"passed": 3},
        cases=[],
        regressions=[],
        verdict="green",
    )


def make_scored_verdict() -> ScoredVerdict:
    return ScoredVerdict(
        id="V-1",
        diff_sha="d1",
        confidence_by_ac={"AC-1": 0.9},
        verdict=VerifierVerdict(per_ac=[], test_integrity_ok=True, overall="ACCEPT"),
    )


def make_finding(fid: str = "F-1") -> Finding:
    return Finding(
        id=fid,
        source_agent="security",
        source_mode="m",
        kind="security",
        severity=Severity.HIGH,
        summary="s",
        payload={},
    )
