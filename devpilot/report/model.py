"""``MissionReport``: the deterministic, evidence-first summary of a mission.

Built only from the event log and the ``Mission`` aggregate (see ``engine.build_report``). Nothing here
is written by an LLM, and nothing is marked verified without execution evidence on the final tree.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from devpilot.core.models import Strict


class EvidenceRef(Strict):
    id: str
    summary: str = ""
    known: bool = True  # False when the id is cited but missing from the ledger


class ACRow(Strict):
    ac_id: str
    text: str
    status: Literal["VERIFIED", "FAILED", "UNVERIFIED", "CLAIMED", "PENDING"]
    priority: str = "must"
    confidence: float | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    reason: str | None = None
    counterexample: str | None = None


class Claim(Strict):
    """A model assertion that no evidence backs. Never rendered under Verified."""

    text: str
    source_agent: str
    source: str  # e.g. "ChangeReport.claims", "MissionSpec.assumptions", "ReviewFinding(proven=false)"
    task_key: str | None = None


class TriageNote(Strict):
    nodeid: str
    fingerprint: str
    error_type: str
    fix_direction: str


class FeedbackLoop(Strict):
    """trigger evidence -> finding -> decision -> next attempt -> outcome, from DECISION events."""

    index: int
    task_key: str | None = None
    trigger_kind: Literal["tests_red", "verifier_reject", "review_reject", "security_block", "other"]
    trigger_text: str
    trigger_evidence: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    finding_kind: str | None = None
    decision_id: str
    action: str
    proposed_action: str | None = None
    cited_evidence: list[str] = Field(default_factory=list)
    guard_override: str | None = None
    next_attempt: int | None = None
    outcome: Literal["green", "red", "accepted", "rejected", "none", "unknown"] = "unknown"
    outcome_evidence: list[str] = Field(default_factory=list)
    triage: list[TriageNote] = Field(default_factory=list)
    fix_summary: str | None = None
    narrative: str = ""


class StrategyChange(Strict):
    seq: int
    task_key: str | None = None
    from_action: str | None = None
    to_action: str
    reason: str


class GuardOverride(Strict):
    seq: int
    task_key: str | None = None
    proposed: str
    final: str
    guard: str
    reason: str


class PlanVersion(Strict):
    version: int
    n_tasks: int
    rationale: str
    revised_because: str | None = None
    task_keys: list[str] = Field(default_factory=list)


class FindingRow(Strict):
    source: Literal["review", "security"]
    lens_or_scanner: str
    severity: str
    location: str
    description: str
    proven: bool
    evidence_ids: list[str] = Field(default_factory=list)


class ReviewSecurity(Strict):
    review_decisions: dict[str, str] = Field(default_factory=dict)  # lens -> latest decision
    security_decision: str | None = None
    findings: list[FindingRow] = Field(default_factory=list)
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    scanners_run: list[str] = Field(default_factory=list)
    scanners_unavailable: list[str] = Field(default_factory=list)


class PreExisting(Strict):
    nodeid: str
    evidence_id: str | None = None
    note: str = ""


class TestSummary(Strict):
    __test__ = False  # not a pytest class

    baseline_totals: dict[str, int] | None = None
    baseline_evidence: str | None = None
    final_totals: dict[str, int] | None = None
    final_evidence: str | None = None
    final_scope: str | None = None
    regressions: list[str] = Field(default_factory=list)
    pre_existing: list[PreExisting] = Field(default_factory=list)


class ChangedFile(Strict):
    path: str
    added: int | None = None
    removed: int | None = None
    source: Literal["diff", "agent-reported"] = "diff"


class BudgetSummary(Strict):
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_total: int = 0
    max_tokens: int = 0
    cost_usd: float = 0.0
    max_cost_usd: float = 0.0
    fix_cycles: int = 0
    max_fix_cycles: int = 0
    wall_clock_s: float = 0.0
    tool_calls: int = 0


class HumanDecisionRow(Strict):
    gate: str
    title: str
    choice: str | None = None
    free_text: str | None = None
    actor: str
    source: str
    at: str  # ISO timestamp


class EvidenceAppendixRow(Strict):
    id: str
    known: bool = True
    kind: str | None = None
    tool: str | None = None
    argv: list[str] | None = None
    exit_code: int | None = None
    workspace_sha: str | None = None
    log_path: str | None = None
    summary: str = ""


class MissionReport(Strict):
    mission_id: str
    request: str
    outcome: str
    outcome_final: bool = True  # False: projected, because the report is written while REPORTING
    outcome_reason: str | None = None
    applied: bool = False
    applied_by: str | None = None
    applied_at: str | None = None
    final_tree_sha: str | None = None

    verified: list[ACRow] = Field(default_factory=list)
    failed: list[ACRow] = Field(default_factory=list)
    unverified: list[ACRow] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    feedback_loops: list[FeedbackLoop] = Field(default_factory=list)
    strategy_changes: list[StrategyChange] = Field(default_factory=list)
    guard_overrides: list[GuardOverride] = Field(default_factory=list)
    plan_history: list[PlanVersion] = Field(default_factory=list)
    review_security: ReviewSecurity = Field(default_factory=ReviewSecurity)
    tests: TestSummary = Field(default_factory=TestSummary)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    budget: BudgetSummary = Field(default_factory=BudgetSummary)
    human_decisions: list[HumanDecisionRow] = Field(default_factory=list)
    evidence_appendix: list[EvidenceAppendixRow] = Field(default_factory=list)
    consistency_errors: list[str] = Field(
        default_factory=list, description="non-empty only when written with force=True"
    )
