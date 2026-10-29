"""EventBridge: ordered delivery of the gateway's sync callbacks onto the blackboard."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from devpilot.core.events import Event, EventType
from devpilot.wiring import EventBridge


class RecordingBoard:
    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[tuple[EventType, str, dict[str, Any], dict[str, Any]]] = []
        self.fail_on = fail_on

    async def emit(self, type: EventType, actor: str, payload: dict[str, Any], **kw: Any) -> None:
        await asyncio.sleep(0)  # force interleaving
        if self.fail_on is not None and payload["i"] == self.fail_on:
            raise RuntimeError("boom")
        self.calls.append((type, actor, payload, kw))


def ev(i: int) -> Event:
    return Event(
        seq=0,
        mission_id="M-x",
        type=EventType.TOOL_CALL,
        actor="samurai#1",
        mode_id="samurai.implement",
        task_key="T1",
        payload={"i": i},
        summary=f"call {i}",
    )


async def test_order_preserved_under_concurrent_callbacks() -> None:
    bb = RecordingBoard()
    bridge = EventBridge(bb)
    bridge.start()

    async def producer(start: int) -> None:
        for i in range(start, start + 50):
            bridge(ev(i))
            await asyncio.sleep(0)

    await asyncio.gather(producer(0), producer(1000))
    await bridge.drain()
    seen = [c[2]["i"] for c in bb.calls]
    assert len(seen) == 100
    assert [i for i in seen if i < 1000] == list(range(50))  # per-producer order kept
    assert [i for i in seen if i >= 1000] == list(range(1000, 1050))
    typ, actor, _, kw = bb.calls[0]
    assert (typ, actor) == (EventType.TOOL_CALL, "samurai#1")
    assert (
        kw["mode_id"] == "samurai.implement" and kw["task_key"] == "T1" and kw["summary"].startswith("call")
    )
    await bridge.close()
    assert bridge.delivered == 100 and bridge.failed == 0


async def test_emit_errors_are_logged_not_raised() -> None:
    bb = RecordingBoard(fail_on=1)
    bridge = EventBridge(bb)
    bridge.start()
    for i in range(3):
        bridge(ev(i))
    await bridge.drain()
    assert [c[2]["i"] for c in bb.calls] == [0, 2]
    assert (bridge.delivered, bridge.failed) == (2, 1)
    await bridge.close()


async def test_callbacks_from_another_thread_are_delivered_in_order() -> None:
    bb = RecordingBoard()
    bridge = EventBridge(bb)
    bridge.start()

    def work() -> None:
        for i in range(20):
            bridge(ev(i))

    t = threading.Thread(target=work)
    t.start()
    await asyncio.to_thread(t.join)
    await asyncio.sleep(0.05)
    await bridge.close()
    assert [c[2]["i"] for c in bb.calls] == list(range(20))


async def test_events_queued_before_start_are_not_lost() -> None:
    bb = RecordingBoard()
    bridge = EventBridge(bb)
    bridge(ev(0))
    bridge.start()
    bridge(ev(1))
    await bridge.close()
    assert [c[2]["i"] for c in bb.calls] == [0, 1]
