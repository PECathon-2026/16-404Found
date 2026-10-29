"""Consistency check, writer refusal, claims separation, projected-outcome edge cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fx2_support import Fx2

from devpilot.core import models as m
from devpilot.report.engine import build_report, consistency_check
from devpilot.report.markdown import render_markdown
from devpilot.report.writer import ReportConsistencyError, write_report


def forged(fx: Fx2) -> m.Mission:
    """AC-2 stays projected as VERIFIED (via AC_STATUS_CHANGED) but its evidence is for another tree."""
    mission = fx.mission.model_copy(deep=True)
    for ev in mission.evidence.values():
        if ev.id == "E-0005":
            ev.workspace_sha = "some-other-tree"
    return mission


def test_consistency_check_flags_projected_verified_without_bound_evidence(fx2: Fx2) -> None:
    mission = forged(fx2)
    assert all(a.status == m.ACStatus.VERIFIED for a in mission.acs)  # what the projection claims
    r = build_report(mission, fx2.events, final_tree_sha=fx2.tree_sha)
    assert r.verified == []  # the engine itself does not trust the projection
    problems = consistency_check(r, mission)
    assert any("AC-2" in p and "projected VERIFIED" in p for p in problems)
    assert any("COMPLETED_VERIFIED" in p for p in problems)


def test_consistency_check_flags_forged_report_row(fx2: Fx2) -> None:
    mission = forged(fx2)
    good = build_report(fx2.mission, fx2.events, final_tree_sha=fx2.tree_sha)
    problems = consistency_check(good, mission)  # honest report, tampered ledger
    assert len([p for p in problems if "without passing execution evidence" in p]) == 2
    assert consistency_check(good, fx2.mission) == []


async def test_writer_refuses_inconsistent_report(fx2: Fx2, tmp_path: Path) -> None:
    out = tmp_path / "out"
    with pytest.raises(ReportConsistencyError) as exc:
        await write_report(forged(fx2), fx2.world.store, fx2.world.ws, out_dir=out)
    assert exc.value.problems
    assert not (out / "REPORT.md").exists()
    assert "refused" in (out / "REPORT_REFUSED.txt").read_text(encoding="utf-8").lower()


async def test_writer_force_adds_red_banner(fx2: Fx2, tmp_path: Path) -> None:
    out = tmp_path / "out"
    md_path = await write_report(forged(fx2), fx2.world.store, fx2.world.ws, out_dir=out, force=True)
    assert md_path == out / "REPORT.md"
    assert "CONSISTENCY CHECK FAILED" in md_path.read_text(encoding="utf-8")
    assert "banner" in (out / "report.html").read_text(encoding="utf-8")
    assert json.loads((out / "mission.json").read_text(encoding="utf-8"))["report"]["consistency_errors"]


async def test_writer_happy_path_writes_all_files_atomically(fx2: Fx2, tmp_path: Path) -> None:
    out = tmp_path / "out"
    await write_report(fx2.mission, fx2.world.store, fx2.world.ws, out_dir=out)
    assert sorted(p.name for p in out.iterdir()) == ["REPORT.md", "final.diff", "mission.json", "report.html"]
    assert "src/pager.py" in (out / "final.diff").read_text(encoding="utf-8")
    assert "+3 -1" in (out / "REPORT.md").read_text(encoding="utf-8")


async def test_writer_without_workspaces_has_no_diff(fx2: Fx2, tmp_path: Path) -> None:
    out = tmp_path / "out"
    await write_report(fx2.mission, fx2.world.store, None, out_dir=out)
    assert not (out / "final.diff").exists()
    md = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "agent-reported, not diff-validated" in md  # falls back, and says so


def test_claims_never_appear_under_verified(fx2: Fx2) -> None:
    mission = fx2.mission.model_copy(deep=True)
    mission.submissions["S-X1"] = m.Submission(
        id="S-X1",
        mode_id="reviewer.review",
        agent_id="reviewer-tests",
        model="scripted",
        output_type="ReviewReport",
        payload=m.ReviewReport(
            lens=m.ReviewLens.TESTS,
            decision="approve",
            findings=[
                m.ReviewFinding(
                    severity="minor",
                    lens=m.ReviewLens.TESTS,
                    location="tests/test_x.py:L3",
                    description="test looks weak",
                    suggestion="assert more",
                    proven=False,
                ),
                m.ReviewFinding(
                    severity="major",
                    lens=m.ReviewLens.TESTS,
                    location="tests/test_x.py:L9",
                    description="proven gap",
                    suggestion="fix",
                    proven=True,
                    evidence_ids=["E-0005"],
                ),
            ],
        ).model_dump(mode="json"),
    )
    assert mission.spec is not None
    mission.spec = mission.spec.model_copy(update={"assumptions": ["pages are 1-indexed"]})
    r = build_report(mission, fx2.events, final_tree_sha=fx2.tree_sha)
    sources = {c.source for c in r.claims}
    assert sources == {"ChangeReport.claims", "MissionSpec.assumptions", "ReviewFinding(proven=false)"}
    texts = " ".join(c.text for c in r.claims)
    assert "test looks weak" in texts and "proven gap" not in texts
    md = render_markdown(r)
    verified = md.split("## ✅ Verified")[1].split("## ❌")[0]
    for c in r.claims:
        assert c.text not in verified
    assert r.review_security.counts_by_severity == {"major": 1, "minor": 1}


def test_unverified_and_failed_rows_carry_reason_and_counterexample(fx2: Fx2) -> None:
    """Build against the first (rejected) tree: AC-2 FAILED with a counterexample, AC-1 verified there."""
    first_tree = fx2.mission.verdicts[0].diff_sha
    r = build_report(fx2.mission, fx2.events, final_tree_sha=first_tree)
    assert [a.ac_id for a in r.verified] == ["AC-1"]
    assert [a.ac_id for a in r.failed] == ["AC-2"]
    assert "total=0" in (r.failed[0].counterexample or "")
    # a tree nobody verified: everything is unverified or claimed, nothing verified
    nothing = build_report(fx2.mission, fx2.events, final_tree_sha="unknown-tree")
    assert nothing.verified == [] and {a.status for a in nothing.unverified} == {"CLAIMED"}
    assert all(a.reason for a in nothing.unverified)
    md = render_markdown(nothing)
    assert "## ⚠️ Unverified" in md and "only an agent's report supports it" in md
    assert consistency_check(nothing, fx2.mission)  # mission says VERIFIED, the evidence says otherwise
