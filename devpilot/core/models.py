"""DevPilot data models — the frozen interface between every subsystem.

Two families of models live here:

* **LLM outputs** (subclass ``LLMOutput``): what an agent submits at the end of a mode via its
  ``submit_*`` tool. They contain *content only* — no IDs, timestamps or bookkeeping that the
  system owns. Their JSON schema is sent to the model, so field descriptions matter.
* **Records** (subclass ``Record``): what the system stores on the blackboard. They carry IDs,
  provenance and timestamps, and may wrap an LLM output.

Changing anything here is an interface change: update ``docs/`` and ping the team.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------------------
# Base classes
# --------------------------------------------------------------------------------------


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, use_enum_values=False)


class LLMOutput(Strict):
    """Base for anything an LLM submits. Schema is exposed to the model as a tool."""


class Record(Strict):
    id: str
    created_at: datetime = Field(default_factory=utcnow)


EvidenceId = Annotated[str, Field(pattern=r"^E-\d{4,}$", description="Evidence ledger id, e.g. E-0021")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Location = Annotated[str, Field(description="workspace-relative 'path:Lstart[-Lend]', e.g. src/pager.py:L41-L44")]


# --------------------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------------------


class AgentRole(StrEnum):
    SHOGUN = "shogun"
    SCOUT = "scout"
    SAMURAI = "samurai"
    SENTINEL = "sentinel"
    VERIFIER = "verifier"
    REVIEWER = "reviewer"
    SECURITY = "security"
    SOLO = "solo"  # single-agent baseline
    HUMAN = "human"
    SYSTEM = "system"  # orchestrator / deterministic components


class ModelTier(StrEnum):
    FRONTIER = "frontier"
    WORKHORSE = "workhorse"
    FAST = "fast"


class MissionStatus(StrEnum):
    CREATED = "CREATED"
    INTEL = "INTEL"  # deterministic repo intelligence
    RECON = "RECON"
    ANALYZING = "ANALYZING"
    CLARIFYING = "CLARIFYING"
    PLANNING = "PLANNING"
    AWAITING_PLAN_APPROVAL = "AWAITING_PLAN_APPROVAL"
    AUTHORING_ACCEPTANCE = "AUTHORING_ACCEPTANCE"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    DECIDING = "DECIDING"
    CHECKING = "CHECKING"
    AWAITING_APPLY = "AWAITING_APPLY"
    APPLYING = "APPLYING"
    REPORTING = "REPORTING"
    COMPLETED_VERIFIED = "COMPLETED_VERIFIED"
    COMPLETED_PARTIAL = "COMPLETED_PARTIAL"
    FAILED = "FAILED"
    ABORTED = "ABORTED"

    @property
    def terminal(self) -> bool:
        return self in {
            MissionStatus.COMPLETED_VERIFIED,
            MissionStatus.COMPLETED_PARTIAL,
            MissionStatus.FAILED,
            MissionStatus.ABORTED,
        }


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    TOURNAMENT = "TOURNAMENT"
    SUBMITTED = "SUBMITTED"
    TESTING = "TESTING"
    REWORK = "REWORK"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class VerificationMethod(StrEnum):
    EXISTING_TEST = "existing_test"
    ACCEPTANCE_TEST = "acceptance_test"  # authored by sentinel.author_acceptance
    PROBE = "probe"  # private verifier probe
    PROPERTY = "property"  # hypothesis-based
    DIFFERENTIAL = "differential"  # baseline vs final behaviour equality
    STATIC_CHECK = "static_check"  # lint / type / scanner
    MANUAL = "manual"  # human must confirm


class ACStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    CLAIMED = "CLAIMED"  # only an agent's assertion supports it


class EvidenceKind(StrEnum):
    TOOL_OUTPUT = "tool_output"
    TEST_RUN = "test_run"
    PROBE_RUN = "probe_run"
    PROPERTY_RUN = "property_run"
    DIFFERENTIAL_RUN = "differential_run"
    MUTATION_RUN = "mutation_run"
    COVERAGE = "coverage"
    SCAN = "scan"
    DIFF = "diff"
    DELTA_DEBUG = "delta_debug"
    HUMAN_INPUT = "human_input"


class Action(StrEnum):
    CONTINUE = "CONTINUE"
    RETRY_SAME_AGENT = "RETRY_SAME_AGENT"
    REASSIGN = "REASSIGN"  # fresh Samurai, no conversation carry-over
    ESCALATE_MODEL = "ESCALATE_MODEL"  # retry on FRONTIER tier
    TOURNAMENT = "TOURNAMENT"  # k diverse candidates in parallel
    INVESTIGATE = "INVESTIGATE"
    REPLAN = "REPLAN"
    ROLLBACK = "ROLLBACK"  # restore best checkpoint, then continue
    ASK_HUMAN = "ASK_HUMAN"
    STOP_PARTIAL = "STOP_PARTIAL"
    ABORT = "ABORT"


class MessageType(StrEnum):
    FINDING = "FINDING"
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    HANDOFF = "HANDOFF"
    VERDICT = "VERDICT"
    DISPUTE = "DISPUTE"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    ESCALATION = "ESCALATION"
    INFO = "INFO"


class Severity(StrEnum):
    CRITICAL = "critical"
    BLOCKER = "blocker"
    HIGH = "high"
    MAJOR = "major"
    MEDIUM = "medium"
    MINOR = "minor"
    LOW = "low"
    NIT = "nit"
    INFO = "info"


class Level(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --------------------------------------------------------------------------------------
# Evidence ledger (written ONLY by the Tool Gateway / deterministic components)
# --------------------------------------------------------------------------------------


class Evidence(Record):
    kind: EvidenceKind
    tool: str
    agent_id: str
    mode_id: str | None = None
    argv: list[str] | None = None
    exit_code: int | None = None
    duration_ms: int = 0
    workspace_ref: str = Field(description="worktree name the evidence was produced in (main|cand-A|baseline|probe)")
    workspace_sha: str = Field(description="git tree hash of that worktree at execution time")
    summary: str
    log_path: str
    sha256: str
    structured: dict[str, Any] = Field(default_factory=dict, description="parsed payload, e.g. junit totals")
    ac_ids: list[str] = Field(default_factory=list, description="acceptance criteria this evidence bears on")


# --------------------------------------------------------------------------------------
# Repo intelligence (deterministic) + Scout recon
# --------------------------------------------------------------------------------------


class Symbol(Strict):
    name: str
    qualname: str
    kind: Literal["function", "method", "class", "variable", "module"]
    path: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    rank: float = 0.0  # personalised PageRank score


class ConventionStat(Strict):
    aspect: Literal[
        "naming", "formatting", "typing", "docstrings", "errors", "structure", "testing", "imports", "logging"
    ]
    observation: str
    confidence: Confidence
    example_ref: Location | None = None


class FileRisk(Strict):
    path: str
    churn: int
    complexity: float
    coverage: float | None
    risk_score: float


class RepoIntel(Strict):
    """Output of the deterministic Repo Intelligence pass (no LLM)."""

    languages: dict[str, int]  # language -> file count
    file_count: int
    test_framework: Literal["pytest", "unittest", "jest", "vitest", "mocha", "unknown"]
    test_command: list[str]
    lint_command: list[str] | None = None
    typecheck_command: list[str] | None = None
    repo_map: list[Symbol]  # top-k ranked symbols
    conventions: list[ConventionStat]
    risks: list[FileRisk]
    test_to_source: dict[str, list[str]] = Field(
        default_factory=dict, description="test nodeid -> ['path:Lx-Ly', ...] from per-test coverage contexts"
    )
    baseline_evidence_id: str | None = None


class RelevantFile(Strict):
    path: str
    reason: str
    symbols: list[str] = Field(default_factory=list)


class RepoBrief(LLMOutput):
    """Scout's interpretation layered on top of RepoIntel."""

    summary: str = Field(description="2-4 sentences: what this repo is and how it is organised")
    relevant_files: list[RelevantFile]
    conventions_confirmed: list[ConventionStat] = Field(
        description="conventions you verified by reading code; refine the mined ones"
    )
    risks: list[str] = Field(description="concrete risks for THIS request, e.g. 'no tests cover rounding'")
    baseline_summary: str = Field(description="e.g. '14 passed, 1 failed (tests/test_dates.py::test_leap)'")
    open_questions: list[str] = Field(default_factory=list)


class InvestigationReport(LLMOutput):
    question: str
    answer: str
    findings: list[str]
    locations: list[Location]
    evidence_ids: list[EvidenceId]
    recommends_replan: bool = False
    new_scope: list[str] = Field(default_factory=list, description="work discovered that is not in the plan")


# --------------------------------------------------------------------------------------
# Mission spec (shogun.analyze)
# --------------------------------------------------------------------------------------


class AcceptanceCriterion(Strict):
    id: str = Field(pattern=r"^AC-\d+$")
    given: str
    when: str
    then: str
    verification_methods: list[VerificationMethod] = Field(min_length=1)
    preserves_existing_behaviour: bool = False
    priority: Literal["must", "should"] = "must"

    @property
    def text(self) -> str:
        return f"Given {self.given}, when {self.when}, then {self.then}"


class ClarifyingOption(Strict):
    key: str
    label: str
    consequence: str


class Ambiguity(Strict):
    level: Level
    question: str | None = None
    options: list[ClarifyingOption] = Field(default_factory=list, max_length=4)
    default_option: str | None = None

    @model_validator(mode="after")
    def _high_needs_question(self) -> Ambiguity:
        if self.level == Level.HIGH and (not self.question or len(self.options) < 2):
            raise ValueError("high ambiguity requires a question and at least 2 options")
        return self


class MissionSpec(LLMOutput):
    restated_request: str
    objectives: list[str]
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    non_goals: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    ambiguity: Ambiguity
    mission_kind: Literal["feature", "bugfix", "test_recovery", "security", "refactor", "other"]

    @model_validator(mode="after")
    def _has_preservation_ac(self) -> MissionSpec:
        if not any(ac.preserves_existing_behaviour for ac in self.acceptance_criteria):
            raise ValueError("include at least one AC with preserves_existing_behaviour=true")
        return self


# --------------------------------------------------------------------------------------
# Plan (shogun.plan / shogun.premortem)
# --------------------------------------------------------------------------------------


class TaskDraft(Strict):
    key: str = Field(pattern=r"^T\d+$")
    title: str
    description: str
    acceptance_refs: list[str]
    files_to_touch: list[str]
    depends_on: list[str] = Field(default_factory=list)
    may_edit_tests: bool = False
    risk: Level = Level.MEDIUM
    strategy_hint: str | None = None


class Plan(LLMOutput):
    rationale: str
    tasks: list[TaskDraft] = Field(min_length=1)
    revised_because: str | None = Field(default=None, description="required on revisions; cite finding/evidence ids")

    @model_validator(mode="after")
    def _dag(self) -> Plan:
        keys = {t.key for t in self.tasks}
        for t in self.tasks:
            missing = set(t.depends_on) - keys
            if missing:
                raise ValueError(f"{t.key} depends on unknown tasks {missing}")
        # cycle check (Kahn)
        indeg = {t.key: len(t.depends_on) for t in self.tasks}
        children: dict[str, list[str]] = {k: [] for k in keys}
        for t in self.tasks:
            for d in t.depends_on:
                children[d].append(t.key)
        queue = [k for k, v in indeg.items() if v == 0]
        seen = 0
        while queue:
            k = queue.pop()
            seen += 1
            for c in children[k]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        if seen != len(self.tasks):
            raise ValueError("task dependencies contain a cycle")
        return self


class WatchCondition(Strict):
    description: str
    trigger: Literal["test_fails", "file_touched", "finding_category", "budget_ratio"]
    pattern: str = Field(description="nodeid glob / path glob / category / ratio threshold")
    response: Action


class PreMortemRisk(Strict):
    failure_story: str
    likelihood: Level
    mitigation: Literal["add_task", "add_ac", "watch", "accept"]
    detail: str


class PreMortem(LLMOutput):
    risks: list[PreMortemRisk]
    watch_conditions: list[WatchCondition] = Field(default_factory=list)
    plan_amendments: Plan | None = Field(default=None, description="full revised plan if mitigations change it")


class Attempt(Strict):
    n: int
    mode_id: str
    agent_id: str
    model: str
    submission_id: str | None = None
    fingerprints: list[str] = Field(default_factory=list)
    hypothesis: str | None = None
    progress: ProgressVector | None = None
    checkpoint_sha: str | None = None
    outcome: Literal["pending", "green", "red", "blocked", "rejected", "superseded"] = "pending"


class Task(Record):
    key: str
    title: str
    description: str
    acceptance_refs: list[str]
    files_to_touch: list[str]
    depends_on: list[str]
    may_edit_tests: bool
    risk: Level
    strategy_hint: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    assignee: str | None = None
    attempts: list[Attempt] = Field(default_factory=list)
    inbox: list[str] = Field(default_factory=list, description="unconsumed message ids")
    plan_version: int


class PlanRecord(Record):
    version: int
    plan: Plan
    premortem: PreMortem | None = None


# --------------------------------------------------------------------------------------
# Acceptance suite (sentinel.author_acceptance) — public, spec-first tests
# --------------------------------------------------------------------------------------


class AcceptanceTest(Strict):
    ac_id: str
    path: str = Field(description="workspace-relative test file, following repo test layout")
    test_names: list[str]
    rationale: str


class AcceptanceSuite(LLMOutput):
    tests: list[AcceptanceTest]
    expected_initial_state: Literal["red", "green", "mixed"] = Field(
        description="before implementation; usually red for new behaviour, green for preservation"
    )
    notes: str = ""


# --------------------------------------------------------------------------------------
# Implementation (samurai.*)
# --------------------------------------------------------------------------------------


class ChangeReport(LLMOutput):
    status: Literal["done", "blocked", "partial"]
    hypothesis: str = Field(description="what you believe is needed / the root cause")
    approach: str
    differs_from_previous: str | None = Field(
        default=None, description="REQUIRED on rework: how this attempt's hypothesis differs from failed ones"
    )
    files_changed: list[str] = Field(description="validated against the real git diff")
    tests_added: list[str] = Field(default_factory=list)
    self_check_evidence_ids: list[EvidenceId] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list, description="assertions not yet independently verified")
    blockers: list[str] = Field(default_factory=list)
    requests: list[str] = Field(default_factory=list, description="questions for Scout/Shogun")


# --------------------------------------------------------------------------------------
# Testing & triage (sentinel.*)
# --------------------------------------------------------------------------------------


class TestOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    XFAIL = "xfail"
    ABSENT = "absent"


class TestClass(StrEnum):
    STILL_PASSING = "still_passing"
    NEWLY_PASSING = "newly_passing"
    REGRESSION = "regression"
    STILL_FAILING = "still_failing"
    EXPECTED_RED = "expected_red"  # acceptance test not yet satisfied
    NEW_PASS = "new_pass"
    NEW_FAIL = "new_fail"
    FLAKY = "flaky"


class TestCaseResult(Strict):
    nodeid: str
    outcome: TestOutcome
    baseline_outcome: TestOutcome
    classification: TestClass
    duration_ms: int = 0
    message: str | None = None
    fingerprint: str | None = None
    is_acceptance: bool = False


class TestRun(Record):
    """Deterministic projection of a test execution (built by the runner, not an LLM)."""

    evidence_id: str
    scope: Literal["targeted", "full", "acceptance", "probe", "baseline"]
    workspace_ref: str
    totals: dict[str, int]
    cases: list[TestCaseResult]
    regressions: list[str]
    verdict: Literal["green", "red", "error"]


class Hypothesis(Strict):
    statement: str
    rank: int
    experiment: str = Field(description="a cheap experiment that would confirm or refute it")
    status: Literal["untested", "confirmed", "refuted", "inconclusive"] = "untested"
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class TriageItem(Strict):
    nodeid: str
    fingerprint: str
    error_type: str
    category: Literal["regression", "expected_red", "pre_existing", "environmental", "flaky"]
    hypotheses: list[Hypothesis] = Field(min_length=1)
    culprit_hunks: list[str] = Field(default_factory=list, description="hunk ids isolated by delta debugging")
    implicated_locations: list[Location]
    fix_direction: str
    confidence: Confidence
    likely_owner_task: str | None = None


class TriageReport(LLMOutput):
    items: list[TriageItem]
    summary: str


# --------------------------------------------------------------------------------------
# Verification (verifier.verify)
# --------------------------------------------------------------------------------------


class CheckResult(Strict):
    method: VerificationMethod
    passed: bool
    evidence_ids: list[EvidenceId]
    detail: str
    metric: float | None = Field(default=None, description="e.g. mutation kill rate, coverage ratio")


class ACVerdict(Strict):
    ac_id: str
    verdict: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    checks: list[CheckResult]
    counterexample: str | None = Field(default=None, description="input -> observed vs expected")
    reasoning: str


class VerifierVerdict(LLMOutput):
    per_ac: list[ACVerdict]
    test_integrity_ok: bool = Field(description="false if existing tests were weakened/skipped")
    integrity_notes: str = ""
    overall: Literal["ACCEPT", "REJECT", "INCONCLUSIVE"]


class ScoredVerdict(Record):
    """Verifier verdict + deterministic confidence, bound to an exact diff."""

    diff_sha: str
    verdict: VerifierVerdict
    confidence_by_ac: dict[str, float]  # computed by report engine, never by the LLM


# --------------------------------------------------------------------------------------
# Review & security
# --------------------------------------------------------------------------------------


class ReviewLens(StrEnum):
    CORRECTNESS = "correctness"
    CONSISTENCY = "consistency"
    TESTS = "tests"
    REGRESSION = "regression"


class ReviewFinding(Strict):
    severity: Literal["blocker", "major", "minor", "nit"]
    lens: ReviewLens
    location: Location
    description: str
    suggestion: str
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    proven: bool = Field(description="true only if evidence demonstrates the problem")


class ReviewReport(LLMOutput):
    lens: ReviewLens
    findings: list[ReviewFinding]
    decision: Literal["approve", "request_changes"]


class TaintPath(Strict):
    source: Location
    sink: Location
    path: list[Location]
    sanitized: bool


class SecurityFinding(Strict):
    severity: Literal["critical", "high", "medium", "low", "info"]
    cwe: str | None = None
    source: Literal["secrets", "bandit", "semgrep", "taint", "fallback_rules", "llm"]
    introduced_by_change: bool
    location: Location
    description: str
    remediation: str
    taint: TaintPath | None = None
    exploit_probe_evidence: EvidenceId | None = None
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class SecurityReport(LLMOutput):
    findings: list[SecurityFinding]
    scanners_run: list[str]
    scanners_unavailable: list[str]
    decision: Literal["pass", "block"]


# --------------------------------------------------------------------------------------
# Unified findings & messaging
# --------------------------------------------------------------------------------------


class Finding(Record):
    source_agent: str
    source_mode: str
    kind: Literal["triage", "review", "security", "investigation", "verifier", "premortem"]
    severity: Severity
    summary: str
    payload: dict[str, Any]
    routed_to: str | None = Field(default=None, description="task key, e.g. 'T2'")
    status: Literal["open", "addressed", "disputed", "wontfix", "escalated", "superseded"] = "open"
    evidence_ids: list[str] = Field(default_factory=list)


class AgentMessage(Record):
    sender: str
    to: str = Field(description="agent id | 'task:T2' | 'topic:<name>' | 'human'")
    type: MessageType
    in_reply_to: str | None = None
    subject: str
    body: str
    refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    consumed_by: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Decisions, disputes, tournaments (shogun.decide / adjudicate / judge.select)
# --------------------------------------------------------------------------------------


class LegalAction(Strict):
    action: Action
    target: str | None = None
    est_tokens: int
    est_seconds: int
    note: str = ""


class DecisionDossier(Strict):
    """Assembled deterministically and given to shogun.decide."""

    trigger_event_seq: int
    trigger_summary: str
    evidence_summaries: dict[str, str]
    task_histories: dict[str, list[Attempt]]
    progress: dict[str, list[ProgressVector]]
    budget: BudgetState
    legal_actions: list[LegalAction]
    open_findings: list[str]


class Decision(LLMOutput):
    action: Action
    target: str | None = None
    justification: str
    cited_evidence: list[EvidenceId] = Field(min_length=1)
    expected_outcome: str
    confidence: Confidence
    fallback_if_fails: Action
    strategy_hints: list[str] = Field(
        default_factory=list, description="TOURNAMENT: k distinct strategies; RETRY: guidance for the agent"
    )
    question_for_human: str | None = None


class DisputeRuling(LLMOutput):
    finding_id: str
    winner: Literal["author", "critic", "undecided"]
    rationale: str
    decisive_evidence: list[EvidenceId]
    escalate_to_human: bool


class CandidateScore(Strict):
    candidate: str  # 'cand-A'
    gates_passed: bool
    gate_failures: list[str]
    public_pass_rate: float
    regressions: int
    mutation_kill_rate: float | None
    lint_issues: int
    diff_lines: int
    convention_similarity: float
    weighted: float


class TournamentResult(LLMOutput):
    winner: str
    rationale: str
    graft_from_losers: list[str] = Field(
        default_factory=list, description="specific ideas worth porting from losing candidates"
    )


# --------------------------------------------------------------------------------------
# Reflection & memory
# --------------------------------------------------------------------------------------


class Lesson(Strict):
    kind: Literal["semantic", "procedural"]
    trigger: str = Field(description="error pattern / situation in which this lesson applies")
    content: str
    evidence_ids: list[EvidenceId] = Field(min_length=1)


class Reflection(LLMOutput):
    what_worked: list[str]
    what_failed: list[str]
    lessons: list[Lesson]


class MemoryItem(Record):
    repo_key: str
    kind: Literal["semantic", "episodic", "procedural"]
    trigger: str
    content: str
    source_mission: str
    evidence_ids: list[str]
    confidence: Confidence = 0.5
    uses: int = 0
    last_validated: datetime | None = None


# --------------------------------------------------------------------------------------
# Human-in-the-loop
# --------------------------------------------------------------------------------------


class HumanPrompt(Record):
    gate: Literal["clarification", "plan", "command", "escalation", "dispute", "apply", "scope"]
    title: str
    body_md: str
    options: list[ClarifyingOption] = Field(default_factory=list)
    allow_free_text: bool = True
    context_refs: list[str] = Field(default_factory=list)
    status: Literal["open", "answered", "expired"] = "open"


class HumanDecision(Record):
    prompt_id: str
    choice: str | None = None
    free_text: str | None = None
    actor: str = "human"
    source: Literal["ui", "cli", "answers_file"] = "ui"


# --------------------------------------------------------------------------------------
# Budgets, progress, accounting
# --------------------------------------------------------------------------------------


class Budgets(Strict):
    max_attempts_per_task: int = 4
    max_fix_cycles: int = 8
    max_replans: int = 2
    max_tournament_k: int = 3
    max_tournaments: int = 2
    max_tokens_mission: int = 1_500_000
    max_cost_usd: float = 15.0
    max_wall_clock_s: int = 1800
    tool_timeout_s: int = 120
    llm_concurrency: int = 4
    max_parallel_samurai: int = 3


class BudgetState(Strict):
    fix_cycles: int = 0
    replans: int = 0
    tournaments: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    tokens_thinking: int = 0
    cost_usd: float = 0.0
    wall_clock_s: float = 0.0
    tool_calls: int = 0
    limits: Budgets = Field(default_factory=Budgets)

    def ratio(self) -> float:
        lim = self.limits
        return max(
            self.fix_cycles / lim.max_fix_cycles,
            (self.tokens_in + self.tokens_out) / lim.max_tokens_mission,
            self.cost_usd / lim.max_cost_usd,
            self.wall_clock_s / lim.max_wall_clock_s,
        )


class ProgressVector(Strict):
    failing_public: int
    failing_fingerprints: list[str]
    regressions: int
    verifier_fails: int

    def dominates(self, other: ProgressVector) -> bool:
        """True if self is at least as good on every axis and strictly better on one."""
        a = (self.failing_public, len(self.failing_fingerprints), self.regressions, self.verifier_fails)
        b = (other.failing_public, len(other.failing_fingerprints), other.regressions, other.verifier_fails)
        return all(x <= y for x, y in zip(a, b, strict=True)) and a != b


class LLMUsage(Strict):
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cached_read: int = 0
    tokens_cache_write: int = 0
    tokens_thinking: int = 0
    cost_usd: float
    latency_ms: int


class Span(Strict):
    """OpenTelemetry-compatible span (exported as OTLP JSON if configured)."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str  # 'mode:samurai.implement' | 'tool:fs.edit' | 'llm:turn'
    start: datetime
    end: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error", "unset"] = "unset"


# --------------------------------------------------------------------------------------
# Mode submissions & mission aggregate
# --------------------------------------------------------------------------------------


class Submission(Record):
    """A validated LLMOutput as stored on the blackboard, with provenance."""

    mode_id: str
    agent_id: str
    model: str
    task_key: str | None = None
    attempt: int | None = None
    output_type: str
    payload: dict[str, Any]
    usage: list[LLMUsage] = Field(default_factory=list)
    thinking_summary: str | None = None


class ACState(Strict):
    ac: AcceptanceCriterion
    status: ACStatus = ACStatus.PENDING
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class Mission(Record):
    request: str
    repo_path: str
    workspace_path: str
    mode: Literal["multi", "single"] = "multi"
    status: MissionStatus = MissionStatus.CREATED
    intel: RepoIntel | None = None
    brief: RepoBrief | None = None
    spec: MissionSpec | None = None
    acs: list[ACState] = Field(default_factory=list)
    plans: list[PlanRecord] = Field(default_factory=list)
    tasks: dict[str, Task] = Field(default_factory=dict)
    submissions: dict[str, Submission] = Field(default_factory=dict)
    test_runs: list[TestRun] = Field(default_factory=list)
    findings: dict[str, Finding] = Field(default_factory=dict)
    messages: dict[str, AgentMessage] = Field(default_factory=dict)
    decisions: list[Submission] = Field(default_factory=list)
    verdicts: list[ScoredVerdict] = Field(default_factory=list)
    prompts: dict[str, HumanPrompt] = Field(default_factory=dict)
    human_decisions: list[HumanDecision] = Field(default_factory=list)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    watch_conditions: list[WatchCondition] = Field(default_factory=list)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)  # {sha, seq, label, progress}
    budget: BudgetState = Field(default_factory=BudgetState)
    last_seq: int = 0
    outcome_reason: str | None = None


# Resolve forward references.
Attempt.model_rebuild()
DecisionDossier.model_rebuild()
