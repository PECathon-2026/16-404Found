"""Mode Registry — every cognitive job DevPilot performs, declared as data.

The orchestrator chooses *which* mode runs next; the AgentRuntime executes a mode generically
from its ModeSpec. Permissions, context visibility (information hiding), model tier, thinking
budget and output contract are all declared here, never improvised in prompts.

Prompts live in ``devpilot/prompts/modes/<mode_id>.md`` and the shared constitution in
``devpilot/prompts/constitution.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from devpilot.core import models as m
from devpilot.core.models import AgentRole, ModelTier

# --------------------------------------------------------------------------------------
# Tool names (dotted display names; the gateway maps them to API-safe names)
# --------------------------------------------------------------------------------------

READ = ("fs.list", "fs.read", "search.code", "search.symbols", "graph.callers", "git.status", "git.diff",
        "git.log")
WRITE = ("fs.edit", "fs.write")
TEST = ("test.run", "test.rerun")
SHELL = ("shell.run",)
LAB = ("lab.differential", "lab.property", "lab.mutation", "lab.coverage", "lab.integrity")
SEC = ("scan.secrets", "scan.sast", "scan.taint")
COMMS = ("board.read", "msg.send")
MEMORY = ("memory.recall",)


class Slice(StrEnum):
    """Blackboard slices a ContextRecipe can include."""

    REQUEST = "request"
    REPO_INTEL = "repo_intel"  # conventions, test cmd, risks (no map)
    REPO_MAP = "repo_map"  # ranked symbols, personalised
    BRIEF = "brief"
    SPEC = "spec"
    ACS = "acs"
    PLAN = "plan"
    PLAN_HISTORY = "plan_history"
    TASK = "task"
    INBOX = "inbox"
    ATTEMPT_HISTORY = "attempt_history"  # hypotheses + fingerprints (+ outcomes)
    CHANGE_REPORT = "change_report"  # Samurai's own narrative — HIDDEN from verifier/reviewers
    DIFF = "diff"
    DIFF_CALLERS = "diff_callers"  # reverse references of changed symbols
    TEST_MATRIX = "test_matrix"  # latest run vs baseline
    TRIAGE = "triage"
    ACCEPTANCE_SUITE = "acceptance_suite"
    FINDINGS_OPEN = "findings_open"
    DOSSIER = "dossier"
    CANDIDATE_SCORES = "candidate_scores"
    MEMORY_SEMANTIC = "memory_semantic"
    MEMORY_PROCEDURAL = "memory_procedural"
    MEMORY_EPISODIC = "memory_episodic"
    EVENT_DIGEST = "event_digest"  # condensed mission timeline (reflection)


@dataclass(frozen=True, slots=True)
class ThinkingPolicy:
    enabled: bool = True
    budget_tokens: int = 4000


@dataclass(frozen=True, slots=True)
class ModeLimits:
    max_steps: int = 25
    max_output_tokens: int = 8000
    wall_clock_s: int = 300
    max_repair_rounds: int = 2  # schema/semantic validation retries


@dataclass(frozen=True, slots=True)
class ModelEscalation:
    on_attempt: int  # attempt number at which to upgrade the tier
    to: ModelTier
    thinking_budget: int


@dataclass(frozen=True, slots=True)
class ContextRecipe:
    slices: tuple[Slice, ...]
    token_budget: dict[Slice, int] = field(default_factory=dict)  # per-slice caps (default 4k)
    hidden: tuple[Slice, ...] = ()  # asserted absent — runtime raises if a recipe includes them


@dataclass(frozen=True, slots=True)
class ModeSpec:
    id: str
    agent: AgentRole
    purpose: str
    tier: ModelTier
    thinking: ThinkingPolicy
    tools: tuple[str, ...]
    output: type[m.LLMOutput]
    context: ContextRecipe
    limits: ModeLimits = ModeLimits()
    escalation: ModelEscalation | None = None
    validators: tuple[str, ...] = ()  # names in engine/validators.py
    writes_workspace: bool = False
    parallel_safe: bool = True

    @property
    def submit_tool(self) -> str:
        return f"submit_{self.output.__name__.lower()}"


VERIFIER_HIDDEN = (Slice.CHANGE_REPORT, Slice.ATTEMPT_HISTORY, Slice.INBOX, Slice.TRIAGE)
REVIEW_HIDDEN = (Slice.CHANGE_REPORT,)

_MODES: tuple[ModeSpec, ...] = (
    # ------------------------------------------------------------------ council
    ModeSpec(
        id="scout.recon",
        agent=AgentRole.SCOUT,
        purpose="Interpret the deterministic RepoIntel for this request; confirm conventions and locate code.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=4000),
        tools=READ + TEST + MEMORY,
        output=m.RepoBrief,
        context=ContextRecipe((Slice.REQUEST, Slice.REPO_INTEL, Slice.REPO_MAP, Slice.MEMORY_SEMANTIC)),
        limits=ModeLimits(max_steps=20, wall_clock_s=240),
        validators=("paths_exist",),
    ),
    ModeSpec(
        id="scout.investigate",
        agent=AgentRole.SCOUT,
        purpose="Answer a specific question raised by a decision or another agent, with evidence.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=8000),
        tools=READ + TEST + SHELL + MEMORY,
        output=m.InvestigationReport,
        context=ContextRecipe((Slice.REQUEST, Slice.BRIEF, Slice.REPO_MAP, Slice.SPEC, Slice.PLAN, Slice.TASK,
                               Slice.ATTEMPT_HISTORY, Slice.TRIAGE, Slice.DIFF, Slice.MEMORY_PROCEDURAL)),
        limits=ModeLimits(max_steps=25, wall_clock_s=300),
        validators=("evidence_exists",),
    ),
    ModeSpec(
        id="shogun.analyze",
        agent=AgentRole.SHOGUN,
        purpose="Convert the request into objectives and Given/When/Then acceptance criteria; detect ambiguity.",
        tier=ModelTier.FRONTIER,
        thinking=ThinkingPolicy(budget_tokens=12000),
        tools=READ + MEMORY,
        output=m.MissionSpec,
        context=ContextRecipe((Slice.REQUEST, Slice.BRIEF, Slice.REPO_INTEL, Slice.REPO_MAP,
                               Slice.MEMORY_SEMANTIC, Slice.MEMORY_EPISODIC)),
        limits=ModeLimits(max_steps=12, wall_clock_s=240),
        validators=("ac_ids_sequential",),
    ),
    ModeSpec(
        id="shogun.plan",
        agent=AgentRole.SHOGUN,
        purpose="Decompose the mission into a task DAG with file ownership, risk and AC coverage.",
        tier=ModelTier.FRONTIER,
        thinking=ThinkingPolicy(budget_tokens=16000),
        tools=READ + MEMORY,
        output=m.Plan,
        context=ContextRecipe((Slice.REQUEST, Slice.BRIEF, Slice.REPO_INTEL, Slice.REPO_MAP, Slice.SPEC,
                               Slice.PLAN_HISTORY, Slice.FINDINGS_OPEN, Slice.MEMORY_PROCEDURAL)),
        limits=ModeLimits(max_steps=12, wall_clock_s=300),
        validators=("plan_covers_all_must_acs", "plan_paths_plausible", "revision_has_reason"),
    ),
    ModeSpec(
        id="shogun.premortem",
        agent=AgentRole.SHOGUN,
        purpose="Assume the plan failed; list likely causes and convert them into mitigations/watch triggers.",
        tier=ModelTier.FRONTIER,
        thinking=ThinkingPolicy(budget_tokens=8000),
        tools=READ,
        output=m.PreMortem,
        context=ContextRecipe((Slice.SPEC, Slice.PLAN, Slice.BRIEF, Slice.REPO_INTEL, Slice.MEMORY_PROCEDURAL)),
        limits=ModeLimits(max_steps=6, wall_clock_s=180),
    ),
    ModeSpec(
        id="shogun.decide",
        agent=AgentRole.SHOGUN,
        purpose="Choose the next action from the legal action set, citing evidence.",
        tier=ModelTier.FRONTIER,
        thinking=ThinkingPolicy(budget_tokens=8000),
        tools=("board.read", "fs.read", "git.diff"),
        output=m.Decision,
        context=ContextRecipe((Slice.REQUEST, Slice.SPEC, Slice.PLAN, Slice.DOSSIER, Slice.TRIAGE, Slice.FINDINGS_OPEN,
                               Slice.MEMORY_PROCEDURAL)),
        limits=ModeLimits(max_steps=6, wall_clock_s=150),
        validators=("evidence_exists", "action_is_legal", "no_repeat_failed_strategy"),
    ),
    ModeSpec(
        id="shogun.adjudicate",
        agent=AgentRole.SHOGUN,
        purpose="Settle a dispute between an author and a critic strictly by evidence.",
        tier=ModelTier.FRONTIER,
        thinking=ThinkingPolicy(budget_tokens=12000),
        tools=READ + ("board.read",),
        output=m.DisputeRuling,
        context=ContextRecipe((Slice.SPEC, Slice.DIFF, Slice.FINDINGS_OPEN, Slice.INBOX)),
        limits=ModeLimits(max_steps=8, wall_clock_s=180),
        validators=("evidence_exists",),
    ),
    ModeSpec(
        id="judge.select",
        agent=AgentRole.SHOGUN,
        purpose="Pick the tournament winner among gate-passing candidates using scores and diffs.",
        tier=ModelTier.FRONTIER,
        thinking=ThinkingPolicy(budget_tokens=8000),
        tools=("git.diff", "fs.read"),
        output=m.TournamentResult,
        context=ContextRecipe((Slice.SPEC, Slice.TASK, Slice.CANDIDATE_SCORES, Slice.REPO_INTEL)),
        limits=ModeLimits(max_steps=6, wall_clock_s=180),
        validators=("winner_passed_gates",),
    ),
    ModeSpec(
        id="shogun.reflect",
        agent=AgentRole.SHOGUN,
        purpose="Extract evidence-backed lessons for memory after the mission ends.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=4000),
        tools=("board.read",),
        output=m.Reflection,
        context=ContextRecipe((Slice.REQUEST, Slice.SPEC, Slice.EVENT_DIGEST, Slice.TRIAGE)),
        limits=ModeLimits(max_steps=4, wall_clock_s=120),
        validators=("evidence_exists",),
    ),
    # ------------------------------------------------------------------ dojo
    ModeSpec(
        id="sentinel.author_acceptance",
        agent=AgentRole.SENTINEL,
        purpose="Write PUBLIC acceptance tests from the spec before implementation, in the repo's test style.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=6000),
        tools=READ + ("fs.write", "fs.edit") + TEST,
        output=m.AcceptanceSuite,
        context=ContextRecipe((Slice.SPEC, Slice.ACS, Slice.BRIEF, Slice.REPO_INTEL, Slice.REPO_MAP)),
        limits=ModeLimits(max_steps=20, wall_clock_s=300),
        validators=("acceptance_files_are_tests_only", "every_must_ac_has_test", "tests_collect"),
        writes_workspace=True,
        parallel_safe=False,
    ),
    ModeSpec(
        id="sentinel.triage",
        agent=AgentRole.SENTINEL,
        purpose="Scientifically diagnose failing tests: classify, hypothesise, experiment (ddmin, probes), conclude.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=10000),
        tools=READ + TEST + ("debug.ddmin", "lab.differential") + MEMORY,
        output=m.TriageReport,
        context=ContextRecipe((Slice.SPEC, Slice.PLAN, Slice.TEST_MATRIX, Slice.DIFF, Slice.REPO_MAP,
                               Slice.ATTEMPT_HISTORY, Slice.MEMORY_PROCEDURAL)),
        limits=ModeLimits(max_steps=25, wall_clock_s=360),
        validators=("evidence_exists", "fingerprints_match_runs"),
    ),
    ModeSpec(
        id="verifier.verify",
        agent=AgentRole.VERIFIER,
        purpose="Independently establish, per AC, execution evidence of satisfaction on the final code.",
        tier=ModelTier.FRONTIER,
        thinking=ThinkingPolicy(budget_tokens=16000),
        tools=READ + ("fs.write_probe",) + TEST + LAB,
        output=m.VerifierVerdict,
        context=ContextRecipe(
            (Slice.SPEC, Slice.ACS, Slice.BRIEF, Slice.REPO_INTEL, Slice.DIFF, Slice.TEST_MATRIX),
            hidden=VERIFIER_HIDDEN,
        ),
        limits=ModeLimits(max_steps=35, max_output_tokens=10000, wall_clock_s=480),
        validators=("evidence_exists", "verdict_covers_all_acs", "pass_requires_execution_evidence"),
    ),
    # ------------------------------------------------------------------ forge
    ModeSpec(
        id="samurai.implement",
        agent=AgentRole.SAMURAI,
        purpose="Implement one task in the worktree following conventions; make public acceptance tests pass.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=6000),
        tools=READ + WRITE + TEST + SHELL + COMMS + MEMORY,
        output=m.ChangeReport,
        context=ContextRecipe((Slice.SPEC, Slice.TASK, Slice.BRIEF, Slice.REPO_INTEL, Slice.REPO_MAP,
                               Slice.ACCEPTANCE_SUITE, Slice.MEMORY_SEMANTIC, Slice.MEMORY_PROCEDURAL)),
        limits=ModeLimits(max_steps=30, wall_clock_s=420),
        escalation=ModelEscalation(on_attempt=3, to=ModelTier.FRONTIER, thinking_budget=12000),
        validators=("files_changed_matches_diff", "within_file_locks", "evidence_exists"),
        writes_workspace=True,
    ),
    ModeSpec(
        id="samurai.rework",
        agent=AgentRole.SAMURAI,
        purpose="Address routed findings; must state how the new hypothesis differs from failed ones.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=10000),
        tools=READ + WRITE + TEST + SHELL + COMMS + MEMORY,
        output=m.ChangeReport,
        context=ContextRecipe((Slice.SPEC, Slice.TASK, Slice.BRIEF, Slice.REPO_INTEL, Slice.REPO_MAP,
                               Slice.ACCEPTANCE_SUITE, Slice.INBOX, Slice.ATTEMPT_HISTORY, Slice.TRIAGE,
                               Slice.DIFF, Slice.MEMORY_PROCEDURAL)),
        limits=ModeLimits(max_steps=30, wall_clock_s=420),
        escalation=ModelEscalation(on_attempt=3, to=ModelTier.FRONTIER, thinking_budget=16000),
        validators=("files_changed_matches_diff", "within_file_locks", "evidence_exists",
                    "rework_states_difference"),
        writes_workspace=True,
    ),
    ModeSpec(
        id="samurai.explore",
        agent=AgentRole.SAMURAI,
        purpose="Tournament candidate: implement the task following ONE assigned strategy in an isolated worktree.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=6000),
        tools=READ + WRITE + TEST + SHELL,
        output=m.ChangeReport,
        context=ContextRecipe((Slice.SPEC, Slice.TASK, Slice.BRIEF, Slice.REPO_INTEL, Slice.REPO_MAP,
                               Slice.ACCEPTANCE_SUITE, Slice.ATTEMPT_HISTORY, Slice.TRIAGE)),
        limits=ModeLimits(max_steps=30, wall_clock_s=420),
        validators=("files_changed_matches_diff",),
        writes_workspace=True,
    ),
    # ------------------------------------------------------------------ shadow council
    ModeSpec(
        id="reviewer.review",
        agent=AgentRole.REVIEWER,
        purpose="Review the diff through ONE lens; blockers/majors must be proven with evidence.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=8000),
        tools=READ + ("test.run", "fs.write_probe") + MEMORY,
        output=m.ReviewReport,
        context=ContextRecipe(
            (Slice.SPEC, Slice.BRIEF, Slice.REPO_INTEL, Slice.DIFF, Slice.DIFF_CALLERS, Slice.TEST_MATRIX,
             Slice.MEMORY_SEMANTIC),
            hidden=REVIEW_HIDDEN,
        ),
        limits=ModeLimits(max_steps=20, wall_clock_s=300),
        validators=("evidence_exists", "unproven_blockers_downgraded"),
    ),
    ModeSpec(
        id="security.inspect",
        agent=AgentRole.SECURITY,
        purpose="Layered security inspection: secrets, SAST, taint, LLM confirmation, optional exploit probe.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=8000),
        tools=READ + SEC + ("fs.write_probe", "test.run"),
        output=m.SecurityReport,
        context=ContextRecipe((Slice.SPEC, Slice.DIFF, Slice.DIFF_CALLERS, Slice.REPO_INTEL), hidden=REVIEW_HIDDEN),
        limits=ModeLimits(max_steps=25, wall_clock_s=360),
        validators=("evidence_exists", "introduced_flag_matches_diff"),
    ),
    # ------------------------------------------------------------------ baseline
    ModeSpec(
        id="single.baseline",
        agent=AgentRole.SOLO,
        purpose="Single-agent baseline: plan, implement, test and self-review alone.",
        tier=ModelTier.WORKHORSE,
        thinking=ThinkingPolicy(budget_tokens=8000),
        tools=READ + WRITE + TEST + SHELL,
        output=m.ChangeReport,
        context=ContextRecipe((Slice.REQUEST, Slice.REPO_INTEL, Slice.REPO_MAP)),
        limits=ModeLimits(max_steps=80, wall_clock_s=1500),
        writes_workspace=True,
        parallel_safe=False,
    ),
)

REGISTRY: dict[str, ModeSpec] = {spec.id: spec for spec in _MODES}


def get(mode_id: str) -> ModeSpec:
    try:
        return REGISTRY[mode_id]
    except KeyError as exc:
        raise KeyError(f"unknown mode {mode_id!r}; known: {sorted(REGISTRY)}") from exc


def _self_check() -> None:
    for spec in _MODES:
        leaked = set(spec.context.slices) & set(spec.context.hidden)
        if leaked:
            raise AssertionError(f"{spec.id}: hidden slices included in recipe: {leaked}")
        if spec.writes_workspace and not (set(spec.tools) & set(WRITE)):
            raise AssertionError(f"{spec.id}: writes_workspace but has no write tools")
        if not spec.writes_workspace and set(spec.tools) & set(WRITE) and spec.agent is not AgentRole.SENTINEL:
            raise AssertionError(f"{spec.id}: has write tools but writes_workspace=False")


_self_check()
