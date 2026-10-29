"""Completion gate (ARCHITECTURE.md §B.5): pure function, unit-tested with a truth table.

Refinement of the blueprint: criteria verified only by manual review come back INCONCLUSIVE from the verifier.
They do not block *requesting* approval, but the approval must explicitly acknowledge them (`needs_ack`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import CriterionStatus, FindingStatus, Severity

OPEN_STATES = {FindingStatus.OPEN, FindingStatus.DISPUTED, FindingStatus.FIX_PROPOSED}


@dataclass
class GateResult:
    clear: bool
    reasons: list[str] = field(default_factory=list)
    needs_ack: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"clear": self.clear, "reasons": self.reasons, "needs_ack": self.needs_ack, "notes": self.notes}


def completion_gate(
    *,
    patch_sha256: str | None,
    criteria: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    verification: dict[str, Any] | None,
    test_runs: list[dict[str, Any]],
    tamper_waived: bool = False,
) -> GateResult:
    reasons: list[str] = []
    notes: list[str] = []
    needs_ack: list[str] = []

    if not patch_sha256:
        reasons.append("no changes: the patch is empty")
    v = verification
    if v is None or v.get("patch_sha256") != patch_sha256:
        reasons.append("no verification for the current patch")
    else:
        if v.get("overall") == "FAIL":
            reasons.append("independent verification failed")
        for r in v.get("results", []):
            st = r.get("status")
            if st == CriterionStatus.FAIL:
                reasons.append(f"{r.get('ac_id')} failed verification")
            elif st == CriterionStatus.INCONCLUSIVE:
                needs_ack.append(r.get("ac_id"))
            elif st != CriterionStatus.PASS:
                reasons.append(f"{r.get('ac_id')} not verified")
        if v.get("error"):
            reasons.append(f"verifier error: {v['error']}")
        tc = v.get("tamper_check") or {}
        if tc.get("modified_existing_tests") and not tamper_waived:
            reasons.append("existing tests were modified (tamper check) without a human waiver")
    covered = {r.get("ac_id") for r in (v or {}).get("results", [])}
    for c in criteria:
        if c["ac_key"] not in covered and v is not None and v.get("patch_sha256") == patch_sha256:
            reasons.append(f"{c['ac_key']} has no verifier result")

    for f in findings:
        if Severity(f["severity"]).rank >= Severity.HIGH.rank and f["status"] in OPEN_STATES:
            reasons.append(f"open {f['severity']} finding: {f['category']} at {f.get('file')}:{f.get('line_start')}")

    cur = [t for t in test_runs if t.get("kind") == "TEST" and t.get("patch_sha256") == patch_sha256]
    latest = cur[-1] if cur else None
    if latest is None:
        reasons.append("no test/check evidence for the current patch")
    elif latest["outcome"] == "NO_TESTS":
        notes.append("the repository has no runnable tests; completion rests on verifier criteria only")
    elif latest["outcome"] != "GREEN":
        reasons.append(f"latest test run on the current patch is {latest['outcome']}")

    return GateResult(clear=not reasons, reasons=reasons, needs_ack=needs_ack, notes=notes)
