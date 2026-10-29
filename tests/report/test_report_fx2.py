"""Report engine on a real FX2 event log (the orchestrator's demo scenario)."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from fx2_support import Fx2, run_fx2

from devpilot.core.events import Event, EventType
from devpilot.report.engine import build_report, consistency_check
from devpilot.report.html import render_html
from devpilot.report.markdown import render_markdown
from devpilot.report.model import MissionReport
from devpilot.state.event_store import JsonlEventStore

GOLDEN = Path(__file__).parent / "golden" / "fx2_report.md"


def report_of(fx: Fx2) -> MissionReport:
    return build_report(fx.mission, fx.events, final_tree_sha=fx.tree_sha, diff_text=fx.world.ws.diff_text)


def hook_time(fx: Fx2) -> tuple[MissionReport, list[Event]]:
    """The report exactly as the orchestrator's hook sees it: mission still REPORTING."""
    snap = fx.world.reports[0]
    events = [e for e in fx.events if e.seq <= snap.last_seq]
    return build_report(snap, events, final_tree_sha=fx.tree_sha, diff_text=fx.world.ws.diff_text), events


def test_verified_failed_claims_split(fx2: Fx2) -> None:
    r = report_of(fx2)
    assert [row.ac_id for row in r.verified] == ["AC-1", "AC-2"]
    assert r.failed == [] and r.unverified == []
    assert all(row.confidence == 1.0 and row.evidence for row in r.verified)
    assert {ref.id for row in r.verified for ref in row.evidence} == {"E-0005"}
    assert [(c.source_agent, c.text) for c in r.claims] == [("samurai#1", "Performance is unchanged")]
    assert r.final_tree_sha == fx2.tree_sha and r.applied and r.applied_by == "human"
    assert consistency_check(r, fx2.mission) == []


def test_exactly_two_feedback_loops_with_chains(fx2: Fx2) -> None:
    r = report_of(fx2)
    assert len(r.feedback_loops) == 2
    one, two = r.feedback_loops
    assert one.narrative == "E-0003 red → triage F-0001 → D-0001 RETRY_SAME_AGENT → attempt 2 green (E-0004)"
    assert one.trigger_kind == "tests_red" and one.outcome == "green"
    assert [(t.fingerprint, t.error_type, t.fix_direction) for t in one.triage] == [
        ("a91f03", "AssertionError", "use ceiling division")
    ]
    assert two.trigger_kind == "verifier_reject" and two.outcome == "accepted"
    assert two.narrative.startswith("Verifier AC-2 FAIL (counterexample total=0")
    assert two.narrative.endswith("D-0002 RETRY_SAME_AGENT → attempt 3 accepted (E-0005)")
    assert "F-0002" in two.narrative and two.guard_override is None
    assert r.guard_overrides == [] and r.strategy_changes == []


def test_review_security_budget_tests_plan(fx2: Fx2) -> None:
    r = report_of(fx2)
    assert set(r.review_security.review_decisions.values()) == {"approve"}
    assert r.review_security.security_decision == "pass" and r.review_security.scanners_run == ["secrets"]
    assert r.tests.baseline_totals == {"passed": 2, "failed": 0} and r.tests.final_evidence == "E-0005"
    assert r.budget.fix_cycles == 2 and r.budget.tokens_total > 0 and r.budget.cost_usd > 0
    assert [p.version for p in r.plan_history] == [1]
    assert [(c.path, c.added, c.removed) for c in r.changed_files] == [("src/pager.py", 3, 1)]
    assert [h.gate for h in r.human_decisions] == ["apply"]


def test_build_is_deterministic(fx2: Fx2) -> None:
    assert report_of(fx2).model_dump_json() == report_of(fx2).model_dump_json()


def test_hook_time_outcome_is_projected(fx2: Fx2) -> None:
    r, _ = hook_time(fx2)
    assert r.outcome == "COMPLETED_VERIFIED" and r.outcome_final is False
    assert "projected" in render_markdown(r)
    assert report_of(fx2).outcome_final is True


def test_markdown_cites_evidence_and_sections(fx2: Fx2) -> None:
    md = render_markdown(report_of(fx2))
    for eid in ("E-0001", "E-0003", "E-0004", "E-0005"):
        assert eid in md
    for heading in (
        "## ✅ Verified",
        "## ❌ Failed",
        "## ⚠️ Unverified",
        "## 🗣️ Model claims (NOT verified)",
        "## 🔁 Feedback loops",
        "## 🔍 Review & Security",
        "## 📋 Plan history",
        "## 🧾 Changed files",
        "## ⏱️ Budget usage",
        "## Pre-existing issues (not addressed)",
        "## Evidence appendix",
    ):
        assert heading in md
    verified = md.split("## ✅ Verified")[1].split("## ❌")[0]
    assert "Performance is unchanged" not in verified
    claims = md.split("## 🗣️ Model claims (NOT verified)")[1].split("## 🔁")[0]
    assert "Performance is unchanged" in claims
    # every verified row cites an evidence id
    rows = [line for line in verified.splitlines() if line.startswith("| AC-")]
    assert len(rows) == 2 and all(re.search(r"E-\d{4}", line) for line in rows)
    assert "1. E-0003 red → triage F-0001 → D-0001 RETRY_SAME_AGENT → attempt 2 green (E-0004)" in md


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.json_blob = ""
        self._in_data = False
        self.external: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        d = dict(attrs)
        if tag == "script" and d.get("id") == "report-data":
            self._in_data = True
        if (tag in ("script", "img", "link") and (d.get("src") or d.get("href"))) or "http" in str(
            d.get("src")
        ):
            self.external.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_data = False

    def handle_data(self, data: str) -> None:
        if self._in_data:
            self.json_blob += data


def test_html_parses_and_embeds_valid_json(fx2: Fx2) -> None:
    r = report_of(fx2)
    html = render_html(r, fx2.events)
    p = _Collector()
    p.feed(html)
    p.close()
    assert {"details", "table", "style", "h1"} <= set(p.tags)
    assert p.external == []  # self-contained
    assert "prefers-color-scheme" in html
    assert json.loads(p.json_blob) == r.model_dump(mode="json")
    assert f"{len(fx2.events)} events" in html


def test_html_escapes_untrusted_text(fx2: Fx2) -> None:
    r = report_of(fx2).model_copy(update={"request": "</script><script>alert(1)</script>"})
    html = render_html(r, fx2.events)
    assert "<script>alert(1)" not in html
    p = _Collector()
    p.feed(html)
    assert json.loads(p.json_blob)["request"] == "</script><script>alert(1)</script>"


async def test_golden_fx2_markdown(fx2: Fx2) -> None:
    r, _ = hook_time(fx2)
    got = normalise(render_markdown(r))
    if not GOLDEN.exists():
        GOLDEN.write_text(got, encoding="utf-8", newline="\n")
    assert got == GOLDEN.read_text(encoding="utf-8")


def normalise(md: str) -> str:
    md = re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC", "<TIMESTAMP>", md)
    return re.sub(r"wall clock \d+m\d\ds", "wall clock <DURATION>", md)


async def test_hook_via_orchestrator_writes_files(tmp_path: Path) -> None:
    """make_report_writer wired as the orchestrator's report_writer hook, reading the real JSONL store."""
    from devpilot.report.writer import make_report_writer

    runs = tmp_path / "runs"
    writer = make_report_writer(JsonlEventStore(runs), None, runs)
    fx = await run_fx2(tmp_path, report_writer=writer)
    out = runs / fx.mission.id
    assert {p.name for p in out.iterdir()} >= {"REPORT.md", "report.html", "mission.json", "events.jsonl"}
    md = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "COMPLETED_VERIFIED" in md and "D-0002" in md
    assert (
        json.loads((out / "mission.json").read_text(encoding="utf-8"))["report"]["mission_id"]
        == fx.mission.id
    )
    assert any(e.type == EventType.REPORT_WRITTEN for e in fx.events)
