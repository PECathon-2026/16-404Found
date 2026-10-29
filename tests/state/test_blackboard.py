"""EventSourcedBlackboard: ownership, serialization, load round-trip and time-travel snapshots."""

from __future__ import annotations

import json

import pytest
from factories import MID, make_mission, make_plan_record, make_spec, make_submission, make_task

from devpilot.core.events import EventType
from devpilot.core.models import HumanPrompt, MissionStatus, TaskStatus
from devpilot.state.blackboard import EventSourcedBlackboard, OwnershipError
from devpilot.state.event_store import JsonlEventStore


async def test_create_emits_mission_created(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    events = await store.read(MID)
    assert [e.type for e in events] == [EventType.MISSION_CREATED]
    assert events[0].actor == "system" and bb.mission.last_seq == 1


async def test_payload_is_pure_json_on_disk(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    sub = make_submission("MissionSpec", make_spec().model_dump(mode="json"))
    await bb.emit(
        EventType.SUBMISSION, "master", {"submission": sub}, mode_id="shogun.analyze", summary="spec"
    )
    lines = store.path_for(MID).read_text(encoding="utf-8").splitlines()
    doc = json.loads(lines[1])
    assert doc["payload"]["submission"]["id"] == "S-1" and doc["mode_id"] == "shogun.analyze"
    assert bb.mission.spec is not None


@pytest.mark.parametrize(
    "type_",
    [
        EventType.STATE_CHANGED,
        EventType.PLAN_ADOPTED,
        EventType.TASK_STATE_CHANGED,
        EventType.AC_STATUS_CHANGED,
        EventType.VERDICT,
        EventType.CHECKPOINT,
        EventType.ROLLBACK,
        EventType.APPLIED,
        EventType.DECISION,
        EventType.MISSION_CREATED,
    ],
)
async def test_system_only_events_rejected_for_agents(store: JsonlEventStore, type_: EventType) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    with pytest.raises(OwnershipError):
        await bb.emit(type_, "samurai#1", {})
    assert len(await store.read(MID)) == 1


async def test_human_decision_requires_human(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    prompt = HumanPrompt(id="P-1", gate="plan", title="t", body_md="b")
    await bb.emit(EventType.HUMAN_PROMPT, "master", {"prompt": prompt})
    payload = {"decision": {"id": "HD-1", "prompt_id": "P-1", "choice": "ok"}}
    with pytest.raises(OwnershipError):
        await bb.emit(EventType.HUMAN_DECISION, "system", payload)
    await bb.emit(EventType.HUMAN_DECISION, "human", payload)
    assert bb.mission.prompts["P-1"].status == "answered"


async def test_ephemeral_emit_does_not_project(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    ev = await bb.emit(EventType.AGENT_TEXT_DELTA, "samurai#1", {"text": "hi"})
    assert ev.seq == 1 and bb.mission.last_seq == 1


async def _drive(bb: EventSourcedBlackboard, n_tool_calls: int) -> dict[int, str]:
    """Run a scripted mission, capturing the live state's JSON after every emit."""
    captured: dict[int, str] = {bb.mission.last_seq: bb.mission.model_dump_json()}

    async def emit(type_: EventType, actor: str, payload: dict[str, object]) -> None:
        ev = await bb.emit(type_, actor, payload)
        captured[ev.seq] = bb.mission.model_dump_json()

    await emit(
        EventType.STATE_CHANGED, "system", {"from": "CREATED", "to": MissionStatus.PLANNING, "reason": "go"}
    )
    spec = make_submission("MissionSpec", make_spec("AC-1", "AC-2").model_dump(mode="json"))
    await emit(EventType.SUBMISSION, "master", {"submission": spec})
    await emit(
        EventType.PLAN_ADOPTED,
        "system",
        {"plan_record": make_plan_record(1, "T1"), "tasks": {"T1": make_task("T1")}},
    )
    await emit(
        EventType.TASK_STATE_CHANGED,
        "system",
        {"task_key": "T1", "to": TaskStatus.IN_PROGRESS, "assignee": "samurai#1"},
    )
    for i in range(n_tool_calls):
        await emit(EventType.TOOL_CALL, "samurai#1", {"i": i})
    await emit(
        EventType.STATE_CHANGED, "system", {"from": "PLANNING", "to": MissionStatus.FAILED, "reason": "x"}
    )
    return captured


async def test_load_roundtrip_equals_live(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    await _drive(bb, 30)
    loaded = await EventSourcedBlackboard.load(store, MID)
    assert loaded.mission.model_dump() == bb.mission.model_dump()
    assert loaded.mission.last_seq == bb.mission.last_seq


async def test_load_without_mission_created_raises(store: JsonlEventStore) -> None:
    with pytest.raises(LookupError):
        await EventSourcedBlackboard.load(store, "ghost")


async def test_snapshot_at_seq_matches_live_across_cache_boundary(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    captured = await _drive(bb, 230)
    assert set(bb._snapshots) == {100, 200}
    last = bb.mission.last_seq
    assert last > 200
    for seq in (1, 2, 3, 4, 5, 99, 100, 101, 150, 199, 200, 201, 202, last - 1):
        assert bb.snapshot(at_seq=seq).model_dump_json() == captured[seq], seq
    assert bb.snapshot(at_seq=last).model_dump_json() == captured[last]


async def test_snapshot_after_load_uses_replayed_cache(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    captured = await _drive(bb, 130)
    loaded = await EventSourcedBlackboard.load(store, MID)
    assert 100 in loaded._snapshots
    assert loaded.snapshot(at_seq=117).model_dump_json() == captured[117]


async def test_snapshot_is_deep_copy(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    await _drive(bb, 3)
    snap = bb.snapshot()
    snap.tasks["T1"].status = TaskStatus.CANCELLED
    assert bb.mission.tasks["T1"].status == TaskStatus.IN_PROGRESS


async def test_snapshot_rejects_seq_zero(store: JsonlEventStore) -> None:
    bb = await EventSourcedBlackboard.create(store, make_mission())
    await _drive(bb, 1)
    with pytest.raises(ValueError):
        bb.snapshot(at_seq=0)
