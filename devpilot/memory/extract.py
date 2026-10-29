"""Deterministic memory extraction at REPORTING (docs/04 section 9, docs/11 section 10). No LLM.

* semantic: the confirmed test command and conventions, only after a review approve and only with evidence;
* episodic: one summary per mission (request -> outcome -> cost -> fix cycles);
* procedural: a lesson per triage item whose feedback loop went green, trigger = error type + fingerprint +
  the triage ``fix_direction``, content = the verified fix with the evidence ids that prove it;
* ``Reflection`` lessons are accepted too, but only when every cited evidence id exists in the ledger.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from devpilot.core.models import MemoryItem, Mission, Reflection, RepoBrief
from devpilot.report.model import MissionReport

SEMANTIC_CONF = 0.6
PROCEDURAL_CONF = 0.6
EPISODIC_CONF = 0.5
EPISODIC_FAILED_CONF = 0.3
REFLECTION_CONF = 0.4


def repo_key_for(repo_path: str | Path) -> str:
    """``sha1(abs repo path)[:12]``."""
    return hashlib.sha1(os.path.abspath(str(repo_path)).encode("utf-8")).hexdigest()[:12]


def _item_id(repo_key: str, kind: str, trigger: str) -> str:
    digest = hashlib.sha1(f"{repo_key}|{kind}|{' '.join(trigger.lower().split())}".encode()).hexdigest()
    return f"MEM-{digest[:10]}"


def _item(
    mission: Mission, kind: str, trigger: str, content: str, evidence: list[str], confidence: float
) -> MemoryItem:
    key = repo_key_for(mission.repo_path)
    return MemoryItem(
        id=_item_id(key, kind, trigger),
        repo_key=key,
        kind=kind,
        trigger=trigger,
        content=content,
        source_mission=mission.id,
        evidence_ids=list(dict.fromkeys(evidence)),
        confidence=confidence,
    )


def _review_approved(mission: Mission) -> bool:
    latest: dict[str, str] = {}
    for sub in mission.submissions.values():
        if sub.output_type == "ReviewReport":
            latest[str(sub.payload.get("lens"))] = str(sub.payload.get("decision"))
    return bool(latest) and all(d == "approve" for d in latest.values())


def _existing(mission: Mission, ids: list[str]) -> list[str]:
    return [e for e in dict.fromkeys(ids) if e in mission.evidence]


def lessons_from_reflection(mission: Mission, reflection: Reflection) -> list[MemoryItem]:
    """Convert reflection lessons; drop any whose evidence ids are not all in ``mission.evidence``."""
    out: list[MemoryItem] = []
    for lesson in reflection.lessons:
        if not lesson.evidence_ids or any(e not in mission.evidence for e in lesson.evidence_ids):
            continue
        out.append(
            _item(
                mission,
                lesson.kind,
                lesson.trigger,
                lesson.content,
                list(lesson.evidence_ids),
                REFLECTION_CONF,
            )
        )
    return out


def extract_memories(mission: Mission, report: MissionReport) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    verified_ev = _existing(mission, [r.id for row in report.verified for r in row.evidence])

    # semantic: only after a review approve, and only when backed by evidence
    if _review_approved(mission):
        baseline_ev = _existing(mission, [e for e in (report.tests.baseline_evidence,) if e])
        if mission.intel is not None and mission.intel.test_command:
            ev = _existing(mission, [mission.intel.baseline_evidence_id or ""]) or baseline_ev or verified_ev
            if ev:
                items.append(
                    _item(
                        mission,
                        "semantic",
                        "test command",
                        "Run the tests with: " + " ".join(mission.intel.test_command),
                        ev,
                        SEMANTIC_CONF,
                    )
                )
        brief = mission.brief
        if isinstance(brief, RepoBrief) and verified_ev:
            for conv in brief.conventions_confirmed:
                items.append(
                    _item(
                        mission,
                        "semantic",
                        f"convention {conv.aspect}",
                        conv.observation,
                        verified_ev[:3],
                        min(SEMANTIC_CONF, conv.confidence),
                    )
                )

    # episodic: always (a failed mission is worth remembering, with lower confidence)
    n_ok = len(report.verified)
    total = n_ok + len(report.failed) + len(report.unverified)
    b = report.budget
    summary = (
        f"Request: {' '.join(mission.request.split())} -> outcome {report.outcome}"
        f"{'' if report.applied else ' (not applied)'}; {n_ok}/{total} acceptance criteria verified; "
        f"cost ${b.cost_usd:.4f}, {b.tokens_total} tokens, {b.fix_cycles} fix cycle(s)."
    )
    items.append(
        _item(
            mission,
            "episodic",
            " ".join(mission.request.split())[:200],
            summary,
            verified_ev,
            EPISODIC_CONF
            if report.outcome == "COMPLETED_VERIFIED" and n_ok == total
            else EPISODIC_FAILED_CONF,
        )
    )

    # procedural: fixes that were verified green after a triaged failure
    for loop in report.feedback_loops:
        if loop.trigger_kind != "tests_red" or loop.outcome != "green" or not loop.triage:
            continue
        ev = _existing(mission, [*loop.trigger_evidence, *loop.outcome_evidence])
        if not ev:
            continue
        for note in loop.triage:
            fix = loop.fix_summary or f"attempt {loop.next_attempt} turned the run green"
            items.append(
                _item(
                    mission,
                    "procedural",
                    f"{note.error_type} {note.fingerprint} {note.fix_direction}",
                    f"Failure {note.nodeid} ({note.error_type}, fingerprint {note.fingerprint}) was fixed. "
                    f"Triage direction: {note.fix_direction}. Fix applied in attempt {loop.next_attempt}: {fix}. "
                    f"Verified by {', '.join(ev)}.",
                    ev,
                    PROCEDURAL_CONF,
                )
            )

    for sub in mission.submissions.values():
        if sub.output_type == "Reflection":
            items += lessons_from_reflection(mission, Reflection.model_validate(sub.payload))
    return items
