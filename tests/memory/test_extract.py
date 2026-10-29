"""Deterministic memory extraction from a real FX2 mission."""

from __future__ import annotations

from pathlib import Path

from fx2_support import Fx2

from devpilot.core import models as m
from devpilot.memory.extract import extract_memories, lessons_from_reflection, repo_key_for
from devpilot.memory.store import SqliteMemoryStore
from devpilot.report.engine import build_report


def report_for(fx: Fx2, mission: m.Mission | None = None):  # type: ignore[no-untyped-def]
    return build_report(mission or fx.mission, fx.events, final_tree_sha=fx.tree_sha)


def test_repo_key_is_sha1_of_abs_path_prefix() -> None:
    import hashlib
    import os

    assert repo_key_for("/some/repo") == hashlib.sha1(os.path.abspath("/some/repo").encode()).hexdigest()[:12]
    assert len(repo_key_for(Path("."))) == 12


def test_fx2_yields_episodic_and_procedural_with_fingerprint(fx2: Fx2) -> None:
    items = extract_memories(fx2.mission, report_for(fx2))
    kinds = sorted(i.kind for i in items)
    assert kinds == ["episodic", "procedural"]  # no repo intel / conventions in the scripted run
    proc = next(i for i in items if i.kind == "procedural")
    assert (
        "a91f03" in proc.trigger
        and "AssertionError" in proc.trigger
        and "use ceiling division" in proc.trigger
    )
    assert "Use ceiling division for the page count" in proc.content
    assert proc.evidence_ids == ["E-0003", "E-0004"]
    assert all(e in fx2.mission.evidence for e in proc.evidence_ids)
    epi = next(i for i in items if i.kind == "episodic")
    assert "COMPLETED_VERIFIED" in epi.content and "2 fix cycle" in epi.content and "$" in epi.content
    assert epi.trigger.startswith("Last page of results")
    assert {i.repo_key for i in items} == {repo_key_for(fx2.mission.repo_path)}
    assert {i.source_mission for i in items} == {fx2.mission.id}
    # extraction is deterministic (ids derive from repo/kind/trigger)
    assert [i.id for i in items] == [i.id for i in extract_memories(fx2.mission, report_for(fx2))]


def test_semantic_memories_need_a_review_approve_and_evidence(fx2: Fx2) -> None:
    mission = fx2.mission.model_copy(deep=True)
    mission.intel = m.RepoIntel(
        languages={"python": 3},
        file_count=3,
        test_framework="pytest",
        test_command=["python", "-m", "pytest", "-q"],
        repo_map=[],
        conventions=[],
        risks=[],
        baseline_evidence_id="E-0001",
    )
    mission.brief = m.RepoBrief(
        summary="s",
        relevant_files=[],
        conventions_confirmed=[
            m.ConventionStat(aspect="typing", observation="all functions are fully typed", confidence=0.9)
        ],
        risks=[],
        baseline_summary="ok",
    )
    items = extract_memories(mission, report_for(fx2, mission))
    sem = {i.trigger: i for i in items if i.kind == "semantic"}
    assert sem["test command"].content == "Run the tests with: python -m pytest -q"
    assert sem["test command"].evidence_ids == ["E-0001"]
    assert sem["convention typing"].evidence_ids and sem["convention typing"].confidence <= 0.6

    # one lens asks for changes -> nothing semantic is written
    for sub in reversed(list(mission.submissions.values())):
        if sub.output_type == "ReviewReport":
            sub.payload["decision"] = "request_changes"
            break
    assert not [i for i in extract_memories(mission, report_for(fx2, mission)) if i.kind == "semantic"]


def test_no_review_at_all_means_no_semantic_memory(fx2: Fx2) -> None:
    mission = fx2.mission.model_copy(deep=True)
    mission.submissions = {k: s for k, s in mission.submissions.items() if s.output_type != "ReviewReport"}
    mission.intel = m.RepoIntel(
        languages={}, file_count=1, test_framework="pytest", test_command=["pytest"], repo_map=[],
        conventions=[], risks=[], baseline_evidence_id="E-0001",
    )  # fmt: skip
    assert not [i for i in extract_memories(mission, report_for(fx2, mission)) if i.kind == "semantic"]


def test_reflection_lessons_with_unknown_evidence_are_dropped(fx2: Fx2) -> None:
    refl = m.Reflection(
        what_worked=["retry"],
        what_failed=[],
        lessons=[
            m.Lesson(kind="procedural", trigger="good lesson", content="c1", evidence_ids=["E-0004"]),
            m.Lesson(kind="semantic", trigger="bad lesson", content="c2", evidence_ids=["E-0004", "E-9999"]),
            m.Lesson(kind="semantic", trigger="ghost", content="c3", evidence_ids=["E-8888"]),
        ],
    )
    kept = lessons_from_reflection(fx2.mission, refl)
    assert [k.trigger for k in kept] == ["good lesson"] and kept[0].evidence_ids == ["E-0004"]

    # and a Reflection stored as a submission is picked up by extract_memories
    mission = fx2.mission.model_copy(deep=True)
    mission.submissions["S-R"] = m.Submission(
        id="S-R",
        mode_id="shogun.reflect",
        agent_id="shogun",
        model="scripted",
        output_type="Reflection",
        payload=refl.model_dump(mode="json"),
    )
    triggers = [i.trigger for i in extract_memories(mission, report_for(fx2, mission))]
    assert "good lesson" in triggers and "bad lesson" not in triggers and "ghost" not in triggers


def test_failed_mission_still_gets_a_low_confidence_episode(fx2: Fx2) -> None:
    r = build_report(fx2.mission, fx2.events, final_tree_sha="no-such-tree")
    epi = next(i for i in extract_memories(fx2.mission, r) if i.kind == "episodic")
    assert epi.confidence < 0.5 and "0/2 acceptance criteria verified" in epi.content


async def test_extracted_lessons_are_recalled_by_new_triage_text(fx2: Fx2, tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "mem.sqlite")
    items = extract_memories(fx2.mission, report_for(fx2))
    for it in items:
        await store.write(it)
    key = repo_key_for(fx2.mission.repo_path)
    got = await store.recall(key, "AssertionError a91f03 in pager", ["procedural"])
    assert len(got) == 1 and "ceiling division" in got[0].content
    # re-running the same mission reinforces rather than duplicating
    for it in items:
        await store.write(it)
    assert len(await store.list_items(key)) == 2
    again = await store.get(got[0].id)
    assert again is not None and again.confidence > 0.6
