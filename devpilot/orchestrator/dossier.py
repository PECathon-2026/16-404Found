"""Decision dossier assembly (docs/11 section 9.1). Pure: reads the mission, never an LLM."""

from __future__ import annotations

import json
import re

from devpilot.core.events import Event
from devpilot.core.models import (
    BudgetState,
    DecisionDossier,
    LegalAction,
    Mission,
    ProgressVector,
)

_EVIDENCE_ID = re.compile(r"E-\d{4,}")
SUMMARY_CHARS = 400


def cited_evidence_ids(event: Event) -> list[str]:
    """Evidence ids mentioned anywhere in the trigger event's payload, in first-seen order."""
    text = json.dumps(event.payload, default=str)
    return list(dict.fromkeys(_EVIDENCE_ID.findall(text)))


def build_dossier(
    mission: Mission,
    trigger_event: Event,
    task_key: str,
    legal: list[LegalAction],
    *,
    budget: BudgetState | None = None,
) -> DecisionDossier:
    """Assemble what ``shogun.decide`` needs.

    Evidence summaries cover the evidence cited by the trigger plus the evidence of every open finding
    (ids unknown to the ledger are skipped). ``task_histories`` and ``progress`` cover every task, with
    ``task_key`` first. ``budget`` lets the orchestrator supply counters the projection does not carry.
    """
    open_findings = [f for f in mission.findings.values() if f.status == "open"]
    ids = cited_evidence_ids(trigger_event)
    for f in open_findings:
        ids.extend(f.evidence_ids)
    summaries: dict[str, str] = {}
    for eid in dict.fromkeys(ids):
        ev = mission.evidence.get(eid)
        if ev is not None:
            summaries[eid] = ev.summary[:SUMMARY_CHARS]
    keys = [task_key, *(k for k in mission.tasks if k != task_key)]
    keys = [k for k in keys if k in mission.tasks]
    progress: dict[str, list[ProgressVector]] = {
        k: [a.progress for a in mission.tasks[k].attempts if a.progress is not None] for k in keys
    }
    return DecisionDossier(
        trigger_event_seq=trigger_event.seq,
        trigger_summary=trigger_event.summary or str(trigger_event.type),
        evidence_summaries=summaries,
        task_histories={k: [a.model_copy(deep=True) for a in mission.tasks[k].attempts] for k in keys},
        progress=progress,
        budget=(budget or mission.budget).model_copy(deep=True),
        legal_actions=legal,
        open_findings=[f.id for f in open_findings],
    )
