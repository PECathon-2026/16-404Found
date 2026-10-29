"""Event-sourced blackboard: the live ``Mission`` aggregate is a projection of the event log.

All mutation goes through ``emit``, which (under one lock, so projection order equals seq order)
enforces who may emit what, persists the event, then folds it into the aggregate with the pure
projector. ``snapshot(at_seq)`` rebuilds historical state by replaying from the nearest cached
snapshot (one is kept every ``SNAPSHOT_EVERY`` events).
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic_core import to_jsonable_python

from devpilot.core.events import EPHEMERAL, Event, EventType
from devpilot.core.models import Mission
from devpilot.core.ports import EventStore
from devpilot.state import projector

SNAPSHOT_EVERY = 100

SYSTEM_ONLY: frozenset[EventType] = frozenset(
    {
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
    }
)
HUMAN_ONLY: frozenset[EventType] = frozenset({EventType.HUMAN_DECISION})


class OwnershipError(Exception):
    """An actor tried to emit an event type it does not own."""


def _blank_mission() -> Mission:
    # MISSION_CREATED overwrites every field, so the placeholder values never leak.
    return Mission(id="", request="", repo_path="", workspace_path="")


def _check_ownership(type_: EventType, actor: str) -> None:
    if type_ in SYSTEM_ONLY and actor != "system":
        raise OwnershipError(f"{type_} may only be emitted by 'system', not {actor!r}")
    if type_ in HUMAN_ONLY and actor != "human":
        raise OwnershipError(f"{type_} may only be emitted by 'human', not {actor!r}")


class EventSourcedBlackboard:
    """``ports.Blackboard`` implementation over an ``EventStore``."""

    def __init__(self, store: EventStore, mission: Mission) -> None:
        self._store = store
        self.mission = mission
        self._lock = asyncio.Lock()
        self._snapshots: dict[int, str] = {}

    @classmethod
    async def create(cls, store: EventStore, mission: Mission) -> EventSourcedBlackboard:
        bb = cls(store, mission)
        await bb.emit(EventType.MISSION_CREATED, "system", {"mission": mission}, summary="Mission created")
        return bb

    @classmethod
    async def load(cls, store: EventStore, mission_id: str) -> EventSourcedBlackboard:
        events = await store.read(mission_id)
        if not events or events[0].type != EventType.MISSION_CREATED:
            raise LookupError(f"mission {mission_id!r} has no MISSION_CREATED event")
        mission = _blank_mission()
        bb = cls(store, mission)
        for ev in events:
            projector.apply(mission, ev)
            bb._maybe_cache(ev.seq)
        return bb

    def _maybe_cache(self, seq: int) -> None:
        if seq > 0 and seq % SNAPSHOT_EVERY == 0 and seq == self.mission.last_seq:
            self._snapshots[seq] = self.mission.model_dump_json()

    async def emit(
        self,
        type: EventType,
        actor: str,
        payload: dict[str, Any],
        *,
        mode_id: str | None = None,
        task_key: str | None = None,
        span_id: str | None = None,
        summary: str = "",
    ) -> Event:
        _check_ownership(type, actor)
        # Serialize first so the log is pure JSON and live projection sees exactly what replay will.
        json_payload: dict[str, Any] = to_jsonable_python(payload)
        async with self._lock:
            draft = Event(
                seq=0,
                mission_id=self.mission.id,
                type=type,
                actor=actor,
                mode_id=mode_id,
                task_key=task_key,
                span_id=span_id,
                payload=json_payload,
                summary=summary,
            )
            stored = await self._store.append(draft)
            if stored.type not in EPHEMERAL:
                projector.apply(self.mission, stored)
                self._maybe_cache(stored.seq)
        return stored

    def snapshot(self, at_seq: int | None = None) -> Mission:
        if at_seq is None or at_seq >= self.mission.last_seq:
            return self.mission.model_copy(deep=True)
        if at_seq < 1:
            raise ValueError("at_seq must be >= 1 (a mission exists from its MISSION_CREATED event)")
        reader = getattr(self._store, "read_sync", None)
        if reader is None:
            raise NotImplementedError("snapshot(at_seq) needs a store that implements read_sync")
        base = max((s for s in self._snapshots if s <= at_seq), default=0)
        mission = Mission.model_validate_json(self._snapshots[base]) if base else _blank_mission()
        for ev in reader(self.mission.id, base + 1, at_seq):
            projector.apply(mission, ev)
        return mission
