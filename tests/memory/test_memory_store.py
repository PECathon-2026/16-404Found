"""SqliteMemoryStore: FTS5 and LIKE-fallback recall, dedup, reinforcement, persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from devpilot.core import models as m
from devpilot.memory.store import SqliteMemoryStore, fts5_available, normalise_trigger

REPO = "repo-aaa"

MODES = [pytest.param(True, id="fts5"), pytest.param(False, id="like-fallback")]


def item(
    trigger: str, content: str, *, kind: str = "procedural", conf: float = 0.5, repo: str = REPO, **kw: object
) -> m.MemoryItem:
    return m.MemoryItem(
        id=kw.pop("id", f"MEM-{abs(hash((trigger, repo, kind))) % 10**8}"),  # type: ignore[arg-type]
        repo_key=repo,
        kind=kind,  # type: ignore[arg-type]
        trigger=trigger,
        content=content,
        source_mission="M-1",
        evidence_ids=["E-0001"],
        confidence=conf,
        **kw,  # type: ignore[arg-type]
    )


@pytest.fixture(params=MODES)
def store(request: pytest.FixtureRequest, tmp_path: Path) -> SqliteMemoryStore:
    if request.param and not fts5_available():
        pytest.skip("sqlite build has no FTS5")
    s = SqliteMemoryStore(tmp_path / "mem" / "memory.sqlite", use_fts=request.param)
    assert s.fts is request.param
    return s


async def seed(store: SqliteMemoryStore) -> None:
    await store.write(
        item("AssertionError a91f03 ceiling division", "use ceiling division for page count", id="A")
    )
    await store.write(item("KeyError config missing", "default the config key before lookup", id="B"))
    await store.write(item("ImportError circular import", "move the import inside the function", id="C"))
    await store.write(item("AssertionError rounding", "round half up not banker's rounding", id="D"))


async def test_recall_ranks_relevant_first_and_scopes_by_repo_and_kind(store: SqliteMemoryStore) -> None:
    await seed(store)
    await store.write(item("AssertionError a91f03 elsewhere", "other repo", repo="repo-bbb", id="E"))
    await store.write(item("AssertionError a91f03 convention", "wrong kind", kind="semantic", id="F"))
    got = await store.recall(REPO, "AssertionError a91f03 ceiling", ["procedural"], k=3)
    assert got[0].id == "A"
    assert "E" not in {g.id for g in got} and "F" not in {g.id for g in got}
    assert await store.recall(REPO, "totally unrelated zebra", ["procedural"]) == []
    assert [g.id for g in await store.recall(REPO, "config key", ["procedural"])] == ["B"]


async def test_confidence_scales_ranking(store: SqliteMemoryStore) -> None:
    await store.write(item("timeout flaky network", "retry with backoff", conf=0.2, id="LOW"))
    await store.write(item("timeout flaky network", "x", kind="semantic", conf=0.9, id="HIGH"))
    got = await store.recall(REPO, "timeout flaky network", ["procedural", "semantic"], k=2)
    assert [g.id for g in got] == ["HIGH", "LOW"]


async def test_recall_increments_uses_and_last_used(store: SqliteMemoryStore) -> None:
    await seed(store)
    first = await store.recall(REPO, "ceiling division", ["procedural"], k=1)
    assert first[0].uses == 1
    second = await store.recall(REPO, "ceiling division", ["procedural"], k=1)
    assert second[0].uses == 2
    with sqlite3.connect(store.path) as conn:
        (last,) = conn.execute("SELECT last_used_at FROM memory WHERE id = 'A'").fetchone()
        (never,) = conn.execute("SELECT last_used_at FROM memory WHERE id = 'B'").fetchone()
    assert last is not None and never is None
    got = await store.get("A")
    assert got is not None and got.uses == 2


async def test_k_limits_results_and_empty_query_falls_back_to_confidence(store: SqliteMemoryStore) -> None:
    await seed(store)
    await store.reinforce("C", 0.3)
    assert len(await store.recall(REPO, "AssertionError", ["procedural"], k=1)) == 1
    top = await store.recall(REPO, "", ["procedural"], k=1)
    assert [t.id for t in top] == ["C"]
    assert await store.recall(REPO, "AssertionError", [], k=5) == []
    assert await store.recall(REPO, "AssertionError", ["procedural"], k=0) == []


async def test_dedup_on_normalised_trigger_boosts_confidence(store: SqliteMemoryStore) -> None:
    await store.write(item("Foo  Bar", "first", conf=0.5, id="ONE"))
    await store.write(
        item(
            "foo bar ",
            "second",
            conf=0.1,
            id="TWO",
        )
    )
    items = await store.list_items(REPO)
    assert len(items) == 1
    only = items[0]
    assert only.id == "ONE" and only.content == "second" and only.confidence == pytest.approx(0.6)
    assert normalise_trigger("Foo  Bar") == "foo bar"
    # same trigger but another kind or repo is a different memory
    await store.write(item("foo bar", "sem", kind="semantic", id="THREE"))
    await store.write(item("foo bar", "other", repo="repo-bbb", id="FOUR"))
    assert len(await store.list_items()) == 3
    # the updated content is what search sees
    assert [g.id for g in await store.recall(REPO, "second", ["procedural"])] == ["ONE"]
    assert await store.recall(REPO, "first", ["procedural"]) == []


async def test_dedup_caps_confidence_and_merges_evidence(store: SqliteMemoryStore) -> None:
    await store.write(item("cap", "c", conf=0.95, id="CAP"))
    await store.write(
        item(
            "cap",
            "c2",
            conf=0.95,
            id="CAP2",
        )
    )
    got = await store.get("CAP")
    assert got is not None and got.confidence == 1.0
    new = item("cap", "c3", id="CAP3")
    new.evidence_ids = ["E-0009"]
    await store.write(new)
    got = await store.get("CAP")
    assert got is not None and got.evidence_ids == ["E-0001", "E-0009"]


async def test_reinforce_clamps(store: SqliteMemoryStore) -> None:
    await store.write(item("clamp", "c", conf=0.5, id="CL"))
    await store.reinforce("CL", 0.9)
    assert (await store.get("CL")).confidence == 1.0  # type: ignore[union-attr]
    await store.reinforce("CL", -5)
    assert (await store.get("CL")).confidence == 0.0  # type: ignore[union-attr]
    await store.reinforce("does-not-exist", 0.1)  # unknown ids are ignored


async def test_persists_across_instances_and_special_characters_are_safe(tmp_path: Path) -> None:
    path = tmp_path / "m.sqlite"
    one = SqliteMemoryStore(path)
    await one.write(item('weird "quote" AND OR NEAR(*)', "50% of 'cases'", id="W"))
    two = SqliteMemoryStore(path)
    got = await two.recall(REPO, 'quote AND "OR" NEAR(*) 50%', ["procedural"])
    assert [g.id for g in got] == ["W"]
    # a query with no usable tokens degrades to confidence order instead of raising
    assert [g.id for g in await two.recall(REPO, "%%%  ***", ["procedural"])] == ["W"]


@pytest.mark.skipif(not fts5_available(), reason="no FTS5")
async def test_enabling_fts_on_existing_db_backfills_index(tmp_path: Path) -> None:
    path = tmp_path / "m.sqlite"
    plain = SqliteMemoryStore(path, use_fts=False)
    await plain.write(item("legacy lesson", "written before fts", id="L"))
    fts = SqliteMemoryStore(path, use_fts=True)
    assert [g.id for g in await fts.recall(REPO, "legacy", ["procedural"])] == ["L"]
