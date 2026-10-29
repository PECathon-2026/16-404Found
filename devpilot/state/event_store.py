"""Append-only JSONL event store: the mission's durable source of truth.

Layout: ``<runs_dir>/<mission_id>/events.jsonl``, one ``Event`` JSON document per line. Because
persisted events are gapless and 1-based, line ``N`` always holds ``seq == N``; readers use that
to slice without parsing the whole file.

Ephemeral events (``events.EPHEMERAL``) are fanned out to live subscribers only. They neither
touch disk nor advance ``seq``; they carry the last persisted seq so the UI can place them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from devpilot.core.events import EPHEMERAL, Event

log = logging.getLogger(__name__)

EVENTS_FILENAME = "events.jsonl"
DEFAULT_QUEUE_SIZE = 10_000
_MISSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class SubscriberLagged(Exception):
    """Raised from a subscription whose queue overflowed; the consumer must resync via ``read``."""


class EventStoreCorruptError(Exception):
    """The events file is damaged somewhere other than a truncated final line."""


@dataclass(slots=True, eq=False)
class _Subscriber:
    queue: asyncio.Queue[Event]
    lagged: bool = False


@dataclass(slots=True)
class _MissionState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    loaded: bool = False
    last_seq: int = 0
    subscribers: set[_Subscriber] = field(default_factory=set)


def _recover_sync(path: Path) -> int:
    """Return the last valid seq, truncating a torn trailing write if one is found."""
    if not path.exists():
        return 0
    data = path.read_bytes()
    pos = 0
    last_seq = 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        if nl == -1:
            break
        try:
            ev = Event.model_validate_json(data[pos:nl])
        except ValueError:
            break
        if ev.seq != last_seq + 1:
            break
        last_seq = ev.seq
        pos = nl + 1
    if pos < len(data):
        bad_nl = data.find(b"\n", pos)
        if bad_nl != -1 and data[bad_nl + 1 :].strip():
            raise EventStoreCorruptError(f"{path}: corrupt event after seq {last_seq} (not a torn tail)")
        log.warning("%s: truncating %d torn bytes after seq %d", path, len(data) - pos, last_seq)
        with path.open("r+b") as f:
            f.truncate(pos)
            f.flush()
            os.fsync(f.fileno())
    return last_seq


def _append_sync(path: Path, line: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Binary mode so Windows does not rewrite "\n" and break the line == seq invariant.
    with path.open("ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_events_sync(path: Path, from_seq: int = 0, to_seq: int | None = None) -> list[Event]:
    """Read persisted events with ``from_seq <= seq <= to_seq`` (inclusive)."""
    if not path.exists():
        return []
    # Dropping the last split element discards both the empty tail and any in-flight partial line.
    lines = path.read_bytes().split(b"\n")[:-1]
    start = max(from_seq, 1) - 1
    return [Event.model_validate_json(line) for line in lines[start:to_seq] if line.strip()]


class JsonlEventStore:
    """``ports.EventStore`` backed by per-mission JSONL files."""

    def __init__(self, runs_dir: Path, *, subscriber_queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._runs_dir = runs_dir
        self._queue_size = subscriber_queue_size
        self._states: dict[str, _MissionState] = {}

    def path_for(self, mission_id: str) -> Path:
        # mission_id becomes a directory name, so refuse anything that could escape runs_dir.
        if not _MISSION_ID_RE.fullmatch(mission_id) or ".." in mission_id:
            raise ValueError(f"invalid mission id: {mission_id!r}")
        return self._runs_dir / mission_id / EVENTS_FILENAME

    def missions(self) -> list[str]:
        if not self._runs_dir.exists():
            return []
        return sorted(p.parent.name for p in self._runs_dir.glob(f"*/{EVENTS_FILENAME}"))

    def _state(self, mission_id: str) -> _MissionState:
        self.path_for(mission_id)  # validates the id before any state is created
        st = self._states.get(mission_id)
        if st is None:
            st = self._states[mission_id] = _MissionState()
        return st

    async def _ensure_loaded(self, mission_id: str, st: _MissionState) -> None:
        # Caller holds st.lock, so recovery runs once and never races an append.
        if not st.loaded:
            st.last_seq = await asyncio.to_thread(_recover_sync, self.path_for(mission_id))
            st.loaded = True

    def _fan_out(self, st: _MissionState, event: Event) -> None:
        for sub in list(st.subscribers):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.lagged = True
                st.subscribers.discard(sub)

    async def append(self, event: Event) -> Event:
        st = self._state(event.mission_id)
        async with st.lock:
            await self._ensure_loaded(event.mission_id, st)
            if event.type in EPHEMERAL:
                stored = event.model_copy(update={"seq": st.last_seq})
            else:
                stored = event.model_copy(update={"seq": st.last_seq + 1})
                line = stored.model_dump_json().encode("utf-8") + b"\n"
                await asyncio.to_thread(_append_sync, self.path_for(event.mission_id), line)
                st.last_seq = stored.seq
            self._fan_out(st, stored)
        return stored

    async def read(self, mission_id: str, from_seq: int = 0, to_seq: int | None = None) -> list[Event]:
        return await asyncio.to_thread(read_events_sync, self.path_for(mission_id), from_seq, to_seq)

    def read_sync(self, mission_id: str, from_seq: int = 0, to_seq: int | None = None) -> list[Event]:
        """Blocking variant for synchronous callers (``Blackboard.snapshot``)."""
        return read_events_sync(self.path_for(mission_id), from_seq, to_seq)

    async def subscribe(self, mission_id: str, from_seq: int = 0) -> AsyncIterator[Event]:
        st = self._state(mission_id)
        sub = _Subscriber(asyncio.Queue(maxsize=self._queue_size))
        # Register before reading history, under the append lock: every event appended later
        # lands in the queue and has seq > high, so history and live never overlap or gap.
        async with st.lock:
            await self._ensure_loaded(mission_id, st)
            st.subscribers.add(sub)
            high = st.last_seq
        try:
            if high >= max(from_seq, 1):
                for ev in await self.read(mission_id, from_seq, high):
                    yield ev
            while True:
                if sub.lagged:
                    raise SubscriberLagged(f"subscriber to {mission_id} fell behind")
                ev = await sub.queue.get()
                if ev.type not in EPHEMERAL and ev.seq <= high:
                    continue
                if ev.type in EPHEMERAL or ev.seq >= from_seq:
                    yield ev
        finally:
            with contextlib.suppress(KeyError):
                st.subscribers.remove(sub)
