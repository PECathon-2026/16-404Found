"""JsonlEventStore: ordering, persistence, ephemerals, subscriptions, lag and crash recovery."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from factories import MID, make_event

from devpilot.core.events import EventType
from devpilot.state.event_store import JsonlEventStore, SubscriberLagged

INFO = EventType.MODE_STARTED
DELTA = EventType.AGENT_TEXT_DELTA


async def test_seq_monotonic_from_one(store: JsonlEventStore) -> None:
    seqs = [(await store.append(make_event(INFO, seq=99))).seq for _ in range(5)]
    assert seqs == [1, 2, 3, 4, 5]


async def test_concurrent_appends_gapless(store: JsonlEventStore) -> None:
    stored = await asyncio.gather(*(store.append(make_event(INFO)) for _ in range(200)))
    assert sorted(e.seq for e in stored) == list(range(1, 201))
    lines = store.path_for(MID).read_bytes().splitlines()
    assert len(lines) == 200
    assert [e.seq for e in await store.read(MID)] == list(range(1, 201))


async def test_read_bounds_inclusive(store: JsonlEventStore) -> None:
    for _ in range(10):
        await store.append(make_event(INFO))
    assert [e.seq for e in await store.read(MID, 3, 6)] == [3, 4, 5, 6]
    assert [e.seq for e in await store.read(MID, 8)] == [8, 9, 10]
    assert [e.seq for e in await store.read(MID, 0, 2)] == [1, 2]
    assert await store.read("nope") == []


async def test_ephemeral_not_persisted_and_no_seq(store: JsonlEventStore) -> None:
    await store.append(make_event(INFO))
    d = await store.append(make_event(DELTA))
    assert d.seq == 1
    nxt = await store.append(make_event(INFO))
    assert nxt.seq == 2
    assert [e.type for e in await store.read(MID)] == [INFO, INFO]


async def test_ephemeral_delivered_live(store: JsonlEventStore) -> None:
    await store.append(make_event(INFO))
    got: list[EventType] = []

    async def consume() -> None:
        async for ev in store.subscribe(MID):
            got.append(ev.type)
            if len(got) == 3:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await store.append(make_event(DELTA))
    await store.append(make_event(INFO))
    await asyncio.wait_for(task, 2)
    assert got == [INFO, DELTA, INFO]


async def test_subscribe_history_plus_live_no_gaps(store: JsonlEventStore) -> None:
    for _ in range(20):
        await store.append(make_event(INFO))
    total = 120
    stop = asyncio.Event()

    async def producer() -> None:
        for _ in range(total - 20):
            await store.append(make_event(INFO))
            await asyncio.sleep(0)
        stop.set()

    seen: list[int] = []

    async def consume() -> None:
        async for ev in store.subscribe(MID, from_seq=10):
            seen.append(ev.seq)
            if ev.seq == total:
                return

    c = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber register while the producer is running
    await producer()
    await asyncio.wait_for(c, 5)
    assert seen == list(range(10, total + 1))


async def test_subscriber_unsubscribes_on_close(store: JsonlEventStore) -> None:
    await store.append(make_event(INFO))
    it = store.subscribe(MID)
    await anext(it)
    st = store._states[MID]
    assert len(st.subscribers) == 1
    await it.aclose()  # type: ignore[attr-defined]
    assert not st.subscribers


async def test_lagging_subscriber_raises(tmp_path: Path) -> None:
    small = JsonlEventStore(tmp_path, subscriber_queue_size=3)
    await small.append(make_event(INFO))
    it = small.subscribe(MID)
    assert (await anext(it)).seq == 1
    for _ in range(10):  # consumer is not reading, queue of 3 overflows
        await small.append(make_event(INFO))
    with pytest.raises(SubscriberLagged):
        await anext(it)
    assert not small._states[MID].subscribers


async def test_crash_recovery_truncates_partial_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    first = JsonlEventStore(tmp_path)
    for _ in range(3):
        await first.append(make_event(INFO))
    path = first.path_for(MID)
    good = path.read_bytes()
    with path.open("ab") as f:
        f.write(b'{"seq": 4, "mission_id": "M-1", "ty')  # torn write

    with caplog.at_level(logging.WARNING):
        second = JsonlEventStore(tmp_path)
        nxt = await second.append(make_event(INFO))
    assert nxt.seq == 4
    assert "truncating" in caplog.text
    assert path.read_bytes().startswith(good)
    assert [e.seq for e in await second.read(MID)] == [1, 2, 3, 4]


@pytest.mark.parametrize("bad", ["../x", "a/b", "C:\\x", "", "..", "a..b", ".hidden", "a\n", "x" * 129])
async def test_invalid_mission_id_rejected(store: JsonlEventStore, bad: str) -> None:
    with pytest.raises(ValueError):
        store.path_for(bad)
    with pytest.raises(ValueError):
        await store.append(make_event(INFO, mid=bad))
    with pytest.raises(ValueError):
        await store.read(bad)


def test_valid_mission_ids_accepted(store: JsonlEventStore) -> None:
    for ok in ("M-1", "m_2.x", "20260101-abc", "x" * 128):
        assert store.path_for(ok).parent.name == ok


async def test_missions_lists_event_files(store: JsonlEventStore) -> None:
    assert store.missions() == []
    await store.append(make_event(INFO, mid="b"))
    await store.append(make_event(INFO, mid="a"))
    assert store.missions() == ["a", "b"]
