# WP-C01 — EventStore + Blackboard

## What I built
- `devpilot/state/event_store.py`: `JsonlEventStore(runs_dir, *, subscriber_queue_size=10_000)` implementing `ports.EventStore`.
  Per-mission lock, gapless seq from 1, fsync'd binary appends via `asyncio.to_thread`, torn-tail recovery (truncate + `logging` warning),
  ephemeral events fan out live only, `subscribe` registers its queue under the lock before reading history, overflow raises `SubscriberLagged`.
  Extras: `missions()`, `path_for()`, `read_sync()` (used by `Blackboard.snapshot`), `EventStoreCorruptError` (mid-file corruption is refused, not truncated).
- `devpilot/state/projector.py`: `apply(mission, event)` plus `ProjectionError`; `HANDLERS: dict[EventType, handler]` with an import-time assertion that every `EventType` is covered.
- `devpilot/state/blackboard.py`: `EventSourcedBlackboard` (`create`, `load`, `emit`, `snapshot`), `OwnershipError`, snapshot cache every 100 events.
- Tests in `tests/state/` (`factories.py` holds the model factories; `conftest.py` has the `store` fixture).

## How to verify
```
python -m pytest -q tests/state   -> 95 passed
python -m pytest -q               -> 102 passed
python -m ruff check devpilot/state tests/state  -> All checks passed
python -m mypy devpilot/state     -> Success: no issues found in 4 source files
```

## Deviations from spec
- The worktree was created from a docs-only commit that lacked `devpilot/core`; I reset the branch to `wp/g01-tooling-ci` (7b44d7c) which contains the frozen contracts. No contract files were modified.
- Because persisted lines are gapless, `read` slices by line index (line N == seq N) instead of parsing every line.
- `subscribe` dedupe is structural (history bounded to `high` captured under the lock; live events always have seq > high) plus a cheap `seq <= high` guard.
- `emit` takes keyword-only `mode_id/task_key/span_id/summary` rather than `**kw`; static conformance to the `Blackboard` Protocol's `**kw: Any` is not asserted.
- `snapshot(at_seq)` needs a store exposing `read_sync` (raises `NotImplementedError` otherwise); `snapshot(None)` or `at_seq >= last_seq` is a deep copy of the live mission. `at_seq < 1` raises `ValueError`.
- HUMAN_DECISION for an unknown prompt raises `ProjectionError` (spec only said to mark the prompt answered).

## Contract change requests
- `ports.EventStore`/`Blackboard`: consider adding a sync `read_sync` (or making `snapshot` async) so `snapshot(at_seq)` does not rely on `getattr` duck-typing.
- `Blackboard.emit(..., **kw: Any)` could list the explicit keyword-only parameters.

## Known gaps
- (Fixed in review round 1) `emit` now validates before persisting: `projector.prepare(mission, event)` parses the payload and checks references without mutating, returning a closure `Callable[[Event], None]` that is run with the stored event after `store.append`. `apply` is `prepare(...)(event)` for replay. Invalid payloads raise `ProjectionError` and nothing is written.
- (Fixed in review round 1) `JsonlEventStore.path_for` rejects mission ids not matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` or containing `..` with `ValueError` (also applied by append/read/subscribe).
- `snapshot(at_seq)` reads the whole events file synchronously (cheap slicing, but O(file size) bytes).
- Event store opens/closes the file per append (simple and crash-safe, not maximum throughput).
- `Event.mission_id` casing/characters are not sanitised for use as a directory name; the API layer should validate ids.
