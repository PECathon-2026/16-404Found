"""ContextAssembler: turns a ``ContextRecipe`` into the briefing a mode sees.

Information hiding is enforced twice: (1) a recipe that includes one of its own ``hidden`` slices is
rejected before anything is rendered, and (2) only the recipe's slices are ever rendered - renderers
are looked up per slice and no other mission field is passed along.

The briefing is split for prompt caching: ``stable`` holds slices that do not change for the whole
mission (request, repo intel, repo map, brief) and ``volatile`` everything else.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from devpilot.core import models as m
from devpilot.core.models import Mission
from devpilot.core.ports import MemoryStore, ModeInvocation, RepoIntelService, Workspaces
from devpilot.engine.errors import HiddenSliceError
from devpilot.engine.modes import ModeSpec, Slice
from devpilot.engine.validators import parse_diff_names

log = logging.getLogger(__name__)

DEFAULT_SLICE_TOKENS = 4000
CHARS_PER_TOKEN = 4
NOT_AVAILABLE = "_(not available)_"

STABLE_SLICES: tuple[Slice, ...] = (Slice.REQUEST, Slice.REPO_INTEL, Slice.REPO_MAP, Slice.BRIEF)


@dataclass(slots=True)
class ContextServices:
    """Optional deterministic services the renderers may consult. Any of them may be absent."""

    workspaces: Workspaces | None = None
    repo_intel: RepoIntelService | None = None
    memory: MemoryStore | None = None
    repo_key: str | None = None


@dataclass(slots=True)
class AssembledContext:
    """The rendered briefing plus what went into it (for MODE_STARTED and the UI)."""

    stable: str
    volatile: str
    included: list[Slice]
    hidden: list[Slice]
    token_estimates: dict[Slice, int] = field(default_factory=dict)


@dataclass(slots=True)
class Body:
    """A renderer's result: Markdown text, plus the ``source`` if it is repo-derived (to be fenced)."""

    text: str
    untrusted_source: str | None = None


@dataclass(slots=True)
class RenderCtx:
    """What a renderer may read. ``diff`` is fetched lazily and at most once per assembly."""

    mission: Mission
    inv: ModeInvocation
    services: ContextServices
    _diff: str | None = None

    @property
    def task(self) -> m.Task | None:
        return self.mission.tasks.get(self.inv.task_key) if self.inv.task_key else None

    async def diff(self) -> str | None:
        if self._diff is None and self.services.workspaces is not None:
            try:
                self._diff = await self.services.workspaces.diff(self.inv.workspace_ref)
            except Exception:
                log.warning("workspaces.diff failed", exc_info=True)
                return None
        return self._diff

    def latest_submission(self, output_type: str, *, task_scoped: bool = False) -> m.Submission | None:
        subs = [s for s in self.mission.submissions.values() if s.output_type == output_type]
        if task_scoped and self.inv.task_key:
            scoped = [s for s in subs if s.task_key == self.inv.task_key]
            subs = scoped or subs
        return max(subs, key=lambda s: s.created_at, default=None)


Renderer = Callable[[RenderCtx], Awaitable[Body | None]]
RENDERERS: dict[Slice, Renderer] = {}
TITLES: dict[Slice, str] = {
    Slice.REPO_INTEL: "Repository intelligence",
    Slice.REPO_MAP: "Repository map",
    Slice.ACS: "Acceptance criteria",
    Slice.DIFF_CALLERS: "Callers of changed symbols",
    Slice.TEST_MATRIX: "Test matrix",
    Slice.CHANGE_REPORT: "Change report",
    Slice.ACCEPTANCE_SUITE: "Acceptance suite",
    Slice.FINDINGS_OPEN: "Open findings",
    Slice.CANDIDATE_SCORES: "Candidate scores",
    Slice.MEMORY_SEMANTIC: "Memory (semantic)",
    Slice.MEMORY_PROCEDURAL: "Memory (procedural)",
    Slice.MEMORY_EPISODIC: "Memory (episodic)",
    Slice.EVENT_DIGEST: "Event digest",
}


def _render(slice_: Slice) -> Callable[[Renderer], Renderer]:
    def deco(fn: Renderer) -> Renderer:
        RENDERERS[slice_] = fn
        return fn

    return deco


def title_of(slice_: Slice) -> str:
    return TITLES.get(slice_) or slice_.value.replace("_", " ").capitalize()


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def truncate(text: str, max_tokens: int) -> str:
    """Cut to ``max_tokens`` (chars/4) with an explicit marker so the model knows data is missing."""
    limit = max_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    cut = len(text) - limit
    return f"{text[:limit]}\n…[truncated {cut} chars; full data in the UI/evidence]"


def fence(source: str, text: str) -> str:
    """Wrap repo-derived text so the model treats instructions inside as data."""
    return f'<untrusted source="{source}">\n{text}\n</untrusted>'


def _bullets(items: list[str], empty: str = "none") -> str:
    return "\n".join(f"- {i}" for i in items) if items else f"- {empty}"


def _dump(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json(indent=1, exclude_none=True)
    return json.dumps(obj, indent=1, default=str)


# ---------------------------------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------------------------------


@_render(Slice.REQUEST)
async def _request(c: RenderCtx) -> Body | None:
    return Body(c.mission.request)


@_render(Slice.REPO_INTEL)
async def _repo_intel(c: RenderCtx) -> Body | None:
    i = c.mission.intel
    if i is None:
        return None
    lines = [
        f"Languages: {', '.join(f'{k} ({v})' for k, v in i.languages.items()) or 'unknown'}; files: {i.file_count}",
        f"Test framework: {i.test_framework}; test command: `{' '.join(i.test_command)}`",
    ]
    if i.lint_command:
        lines.append(f"Lint: `{' '.join(i.lint_command)}`")
    if i.typecheck_command:
        lines.append(f"Typecheck: `{' '.join(i.typecheck_command)}`")
    lines.append("Conventions:")
    lines += [f"- {k.aspect}: {k.observation} (conf {k.confidence:.2f})" for k in i.conventions]
    lines.append("Riskiest files:")
    lines += [
        f"- {r.path} risk={r.risk_score:.2f} churn={r.churn}"
        for r in sorted(i.risks, key=lambda r: -r.risk_score)[:10]
    ]
    if i.baseline_evidence_id:
        lines.append(f"Baseline test evidence: {i.baseline_evidence_id}")
    return Body("\n".join(lines))


@_render(Slice.REPO_MAP)
async def _repo_map(c: RenderCtx) -> Body | None:
    i = c.mission.intel
    if i is None or not i.repo_map:
        return None
    syms = sorted(i.repo_map, key=lambda s: -s.rank)
    lines = [
        f"- {s.qualname} ({s.kind}) {s.path}:L{s.line_start}-L{s.line_end}"
        + (f" `{s.signature}`" if s.signature else "")
        for s in syms
    ]
    return Body("\n".join(lines), "repo_map")


@_render(Slice.BRIEF)
async def _brief(c: RenderCtx) -> Body | None:
    b = c.mission.brief
    if b is None:
        return None
    lines = [b.summary, "Relevant files:"]
    lines += [
        f"- {f.path}: {f.reason}" + (f" [{', '.join(f.symbols)}]" if f.symbols else "")
        for f in b.relevant_files
    ]
    lines.append("Conventions confirmed:")
    lines += [f"- {k.aspect}: {k.observation}" for k in b.conventions_confirmed]
    lines += ["Risks:", _bullets(b.risks), f"Baseline: {b.baseline_summary}"]
    if b.open_questions:
        lines += ["Open questions:", _bullets(b.open_questions)]
    return Body("\n".join(lines))


@_render(Slice.SPEC)
async def _spec(c: RenderCtx) -> Body | None:
    s = c.mission.spec
    if s is None:
        return None
    lines = [
        f"Restated request: {s.restated_request}",
        f"Kind: {s.mission_kind}",
        "Objectives:",
        _bullets(s.objectives),
    ]
    for label, items in (
        ("Non-goals", s.non_goals),
        ("Assumptions", s.assumptions),
        ("Constraints", s.constraints),
    ):
        if items:
            lines += [f"{label}:", _bullets(items)]
    return Body("\n".join(lines))


@_render(Slice.ACS)
async def _acs(c: RenderCtx) -> Body | None:
    if not c.mission.acs:
        return None
    lines = []
    for st in c.mission.acs:
        ac = st.ac
        flag = " [preserves existing behaviour]" if ac.preserves_existing_behaviour else ""
        methods = ", ".join(v.value for v in ac.verification_methods)
        lines.append(f"- {ac.id} ({ac.priority}, {st.status.value}){flag}: {ac.text}; verify via {methods}")
    return Body("\n".join(lines))


@_render(Slice.PLAN)
async def _plan(c: RenderCtx) -> Body | None:
    if not c.mission.plans:
        return None
    rec = c.mission.plans[-1]
    lines = [f"Plan v{rec.version}: {rec.plan.rationale}"]
    for t in rec.plan.tasks:
        live = c.mission.tasks.get(t.key)
        status = live.status.value if live else "?"
        lines.append(
            f"- {t.key} [{status}] {t.title}; ACs {', '.join(t.acceptance_refs)}; "
            f"files {', '.join(t.files_to_touch)}; depends on {', '.join(t.depends_on) or 'nothing'}"
        )
    return Body("\n".join(lines))


@_render(Slice.PLAN_HISTORY)
async def _plan_history(c: RenderCtx) -> Body | None:
    if not c.mission.plans:
        return None
    lines = []
    for rec in c.mission.plans:
        lines.append(
            f"- v{rec.version}: {rec.plan.rationale} (tasks: {', '.join(t.key for t in rec.plan.tasks)})"
        )
        if rec.plan.revised_because:
            lines.append(f"  revised because: {rec.plan.revised_because}")
    return Body("\n".join(lines))


@_render(Slice.TASK)
async def _task(c: RenderCtx) -> Body | None:
    t = c.task
    if t is None:
        return None
    lines = [
        f"{t.key}: {t.title} [{t.status.value}, risk {t.risk.value}]",
        t.description,
        f"Acceptance refs: {', '.join(t.acceptance_refs)}",
        f"Files you may touch: {', '.join(t.files_to_touch) or 'none declared'}",
        f"May edit tests: {t.may_edit_tests}; depends on: {', '.join(t.depends_on) or 'nothing'}; attempts so far: {len(t.attempts)}",
    ]
    if t.strategy_hint:
        lines.append(f"Strategy hint: {t.strategy_hint}")
    return Body("\n".join(lines))


@_render(Slice.INBOX)
async def _inbox(c: RenderCtx) -> Body | None:
    t = c.task
    if t is None:
        return None
    msgs = [c.mission.messages[i] for i in t.inbox if i in c.mission.messages]
    if not msgs:
        return Body("_(inbox empty)_")
    lines = []
    for msg in msgs:
        ev = f" evidence: {', '.join(msg.evidence_ids)}" if msg.evidence_ids else ""
        lines.append(f"- [{msg.type.value}] from {msg.sender}: {msg.subject} - {msg.body}{ev}")
    return Body("\n".join(lines))


@_render(Slice.ATTEMPT_HISTORY)
async def _attempt_history(c: RenderCtx) -> Body | None:
    t = c.task
    if t is None:
        return None
    if not t.attempts:
        return Body("_(no previous attempts)_")
    lines = []
    for a in t.attempts:
        fps = ", ".join(a.fingerprints) or "none"
        lines.append(f"- attempt {a.n} ({a.mode_id}, {a.model}): outcome {a.outcome}; fingerprints {fps}")
        if a.hypothesis:
            lines.append(f"  hypothesis: {a.hypothesis}")
    return Body("\n".join(lines))


@_render(Slice.CHANGE_REPORT)
async def _change_report(c: RenderCtx) -> Body | None:
    sub = c.latest_submission("ChangeReport", task_scoped=True)
    if sub is None:
        return None
    p = sub.payload
    lines = [
        f"Status: {p.get('status')}",
        f"Hypothesis: {p.get('hypothesis')}",
        f"Approach: {p.get('approach')}",
        f"Files changed: {', '.join(p.get('files_changed', []))}",
    ]
    for key in ("differs_from_previous", "claims", "blockers", "requests"):
        if p.get(key):
            lines.append(f"{key}: {p[key]}")
    return Body("\n".join(lines))


@_render(Slice.DIFF)
async def _diff(c: RenderCtx) -> Body | None:
    diff = await c.diff()
    if not diff:
        return None if diff is None else Body("_(no changes)_")
    return Body(diff, "diff")


@_render(Slice.DIFF_CALLERS)
async def _diff_callers(c: RenderCtx) -> Body | None:
    ri = c.services.repo_intel
    diff = await c.diff()
    intel = c.mission.intel
    if ri is None or diff is None or intel is None:
        return None
    changed = set(parse_diff_names(diff))
    syms = [s for s in intel.repo_map if s.path in changed][:30]
    if not syms:
        return Body("_(no ranked symbols in changed files)_")
    lines = []
    for s in syms:
        try:
            callers = ri.callers_of(s.qualname)
        except Exception:
            log.warning("callers_of failed for %s", s.qualname, exc_info=True)
            continue
        lines.append(f"- {s.qualname}: {', '.join(callers[:15]) if callers else 'no callers found'}")
    return Body("\n".join(lines), "repo_intel:callers") if lines else None


@_render(Slice.TEST_MATRIX)
async def _test_matrix(c: RenderCtx) -> Body | None:
    if not c.mission.test_runs:
        return None
    run = c.mission.test_runs[-1]
    totals = ", ".join(f"{k}={v}" for k, v in run.totals.items())
    lines = [
        f"Latest run ({run.scope}, {run.workspace_ref}): {run.verdict}; {totals}; evidence {run.evidence_id}"
    ]
    if run.regressions:
        lines.append(f"Regressions vs baseline: {', '.join(run.regressions)}")
    bad = {m.TestOutcome.FAILED, m.TestOutcome.ERROR}
    cases = sorted(run.cases, key=lambda cs: (cs.outcome not in bad, cs.nodeid))
    for cs in cases:
        msg = f" - {cs.message[:200]!r}" if cs.message else ""
        fp = f" fp={cs.fingerprint}" if cs.fingerprint else ""
        lines.append(
            f"- {cs.nodeid}: {cs.outcome.value} (baseline {cs.baseline_outcome.value}, {cs.classification.value}){fp}{msg}"
        )
    return Body("\n".join(lines), f"test_run:{run.evidence_id}")


@_render(Slice.TRIAGE)
async def _triage(c: RenderCtx) -> Body | None:
    sub = c.latest_submission("TriageReport")
    if sub is None:
        return None
    rep = m.TriageReport.model_validate(sub.payload)
    lines = [rep.summary]
    for it in rep.items:
        top = max(it.hypotheses, key=lambda h: -h.rank)
        lines.append(
            f"- {it.nodeid} [{it.category}, {it.fingerprint}] {it.error_type}; "
            f"locations {', '.join(it.implicated_locations)}; fix: {it.fix_direction}; hypothesis: {top.statement}"
        )
    return Body("\n".join(lines))


@_render(Slice.ACCEPTANCE_SUITE)
async def _acceptance_suite(c: RenderCtx) -> Body | None:
    sub = c.latest_submission("AcceptanceSuite")
    if sub is None:
        return None
    suite = m.AcceptanceSuite.model_validate(sub.payload)
    lines = [f"Expected initial state: {suite.expected_initial_state}"]
    lines += [f"- {t.ac_id}: {t.path} ({', '.join(t.test_names)}) - {t.rationale}" for t in suite.tests]
    return Body("\n".join(lines))


@_render(Slice.FINDINGS_OPEN)
async def _findings_open(c: RenderCtx) -> Body | None:
    open_ = [f for f in c.mission.findings.values() if f.status == "open"]
    if not open_:
        return Body("_(no open findings)_")
    return Body(
        "\n".join(
            f"- {f.id} [{f.severity.value}, {f.kind}] routed to {f.routed_to or '-'}: {f.summary}"
            for f in open_
        )
    )


@_render(Slice.DOSSIER)
async def _dossier(c: RenderCtx) -> Body | None:
    d = c.inv.extra_context.get("dossier")
    if d is None:
        return None
    return Body(_dump(d))


@_render(Slice.CANDIDATE_SCORES)
async def _candidate_scores(c: RenderCtx) -> Body | None:
    raw = c.inv.extra_context.get("candidate_scores")
    if not raw:
        return None
    lines = []
    for s in raw:
        cs = s if isinstance(s, m.CandidateScore) else m.CandidateScore.model_validate(s)
        gates = "passed" if cs.gates_passed else f"FAILED ({'; '.join(cs.gate_failures)})"
        lines.append(
            f"- {cs.candidate}: gates {gates}; public pass rate {cs.public_pass_rate:.2f}; regressions {cs.regressions}; "
            f"mutation kill {cs.mutation_kill_rate}; lint {cs.lint_issues}; diff lines {cs.diff_lines}; "
            f"convention similarity {cs.convention_similarity:.2f}; weighted {cs.weighted:.3f}"
        )
    return Body("\n".join(lines))


def _memory_renderer(kind: str) -> Renderer:
    async def render(c: RenderCtx) -> Body | None:
        mem, key = c.services.memory, c.services.repo_key
        if mem is None or key is None:
            return None
        try:
            items = await mem.recall(key, c.mission.request, [kind], 5)
        except Exception:
            log.warning("memory.recall failed", exc_info=True)
            return None
        if not items:
            return Body("_(nothing recalled)_")
        return Body(
            "\n".join(f"- ({i.confidence:.2f}) when {i.trigger}: {i.content}" for i in items),
            f"memory:{kind}",
        )

    return render


RENDERERS[Slice.MEMORY_SEMANTIC] = _memory_renderer("semantic")
RENDERERS[Slice.MEMORY_PROCEDURAL] = _memory_renderer("procedural")
RENDERERS[Slice.MEMORY_EPISODIC] = _memory_renderer("episodic")


@_render(Slice.EVENT_DIGEST)
async def _event_digest(c: RenderCtx) -> Body | None:
    d = c.inv.extra_context.get("event_digest")
    if not d:
        return None
    return Body(d if isinstance(d, str) else "\n".join(f"- {x}" for x in d))


_missing = set(Slice) - set(RENDERERS)
assert not _missing, f"slices without a renderer: {sorted(_missing)}"

ASSIGNMENT_KEYS: tuple[tuple[str, str], ...] = (
    ("lens", "Review lens"),
    ("strategy_hint", "Strategy to follow"),
    ("question", "Question to answer"),
)


class ContextAssembler:
    """Renders the slices of a mode's ``ContextRecipe`` into ``stable`` and ``volatile`` Markdown."""

    async def assemble(
        self, spec: ModeSpec, mission: Mission, inv: ModeInvocation, services: ContextServices
    ) -> AssembledContext:
        recipe = spec.context
        leaked = set(recipe.slices) & set(recipe.hidden)
        if leaked:
            raise HiddenSliceError(
                f"{spec.id}: hidden slices present in recipe: {sorted(s.value for s in leaked)}"
            )
        ctx = RenderCtx(mission, inv, services)
        stable: list[str] = []
        volatile: list[str] = []
        estimates: dict[Slice, int] = {}
        slices = [s for s in STABLE_SLICES if s in recipe.slices]
        slices += [s for s in recipe.slices if s not in STABLE_SLICES]
        for sl in slices:
            section = await self._section(sl, ctx, recipe.token_budget.get(sl, DEFAULT_SLICE_TOKENS))
            estimates[sl] = estimate_tokens(section)
            (stable if sl in STABLE_SLICES else volatile).append(section)
        assignment = [
            f"- {label}: {inv.extra_context[key]}"
            for key, label in ASSIGNMENT_KEYS
            if inv.extra_context.get(key)
        ]
        if assignment:
            volatile.append("## Assignment\n" + "\n".join(assignment))
        return AssembledContext(
            stable="\n\n".join(stable),
            volatile="\n\n".join(volatile),
            included=list(recipe.slices),
            hidden=list(recipe.hidden),
            token_estimates=estimates,
        )

    async def _section(self, sl: Slice, ctx: RenderCtx, max_tokens: int) -> str:
        heading = f"## {title_of(sl)}"
        try:
            body = await RENDERERS[sl](ctx)
        except Exception:
            log.warning("renderer for %s failed", sl, exc_info=True)
            body = None
        if body is None or not body.text.strip():
            return f"{heading}\n{NOT_AVAILABLE}"
        text = truncate(body.text, max_tokens)
        if body.untrusted_source:
            text = fence(body.untrusted_source, text)
        return f"{heading}\n{text}"
