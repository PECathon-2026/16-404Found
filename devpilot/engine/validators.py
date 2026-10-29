"""Semantic validators for mode outputs (the second validation layer after pydantic).

A validator returns a list of human-readable errors (empty = ok). The errors are sent back to the model
verbatim as the ``submit_*`` tool_result, so they should say what to fix. A validator whose backing
service is unavailable returns ``[]`` and logs at debug level: missing infrastructure must never block a
mission, only the deterministic checks that can actually be evaluated are enforced.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from devpilot.core import models as m
from devpilot.core.models import Action, DecisionDossier, EvidenceKind, LLMOutput, Mission
from devpilot.core.ports import ModeInvocation
from devpilot.engine import modes

log = logging.getLogger(__name__)

_EVIDENCE_RE = re.compile(r"\bE-\d{4,}\b")
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$", re.MULTILINE)
_PLUS_HEADER_RE = re.compile(r"^\+\+\+ b/(?P<p>.+)$", re.MULTILINE)
_LOCATION_RE = re.compile(r"^(?P<path>.+?):L?(?P<start>\d+)(?:-L?(?P<end>\d+))?$")
_TEST_BASENAME_PATTERNS = ("test_*.py", "*_test.py", "*.spec.ts", "*.test.ts", "*.spec.js", "*.test.js")
_EXECUTION_EVIDENCE = frozenset(
    {
        EvidenceKind.TEST_RUN,
        EvidenceKind.PROBE_RUN,
        EvidenceKind.PROPERTY_RUN,
        EvidenceKind.DIFFERENTIAL_RUN,
    }
)


def norm_path(path: str) -> str:
    """Normalise a workspace-relative path for comparison (posix separators, no ``./``)."""
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def parse_diff_names(diff: str) -> list[str]:
    """Changed file names (new side) from a unified diff, in order, de-duplicated."""
    names = [mt.group("b") for mt in _DIFF_HEADER_RE.finditer(diff)]
    if not names:
        names = [mt.group("p") for mt in _PLUS_HEADER_RE.finditer(diff)]
    return list(dict.fromkeys(norm_path(n) for n in names))


def is_test_file(path: str) -> bool:
    """True for ``tests/**``, ``test_*.py``, ``*_test.py``, ``*.spec.ts`` (plus common JS variants)."""
    p = norm_path(path)
    parts = p.split("/")
    if "tests" in parts[:-1]:
        return True
    base = parts[-1]
    return any(fnmatch.fnmatch(base, pat) for pat in _TEST_BASENAME_PATTERNS)


@dataclass(slots=True)
class ValidationContext:
    """Everything a validator may consult. Optional callables are ``None`` when the service is absent."""

    mission: Mission
    inv: ModeInvocation
    ledger_exists: Callable[[str], bool] | None = None
    diff_names: Callable[[], Awaitable[list[str]]] | None = None
    collect_tests: Callable[[list[str]], Awaitable[bool]] | None = None
    hunk_paths: Callable[[], Awaitable[list[str]]] | None = None
    path_exists: Callable[[str], Awaitable[bool]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def evidence_exists(self, evidence_id: str) -> bool:
        """True if the id is in the mission's evidence map or the optional ledger port."""
        if evidence_id in self.mission.evidence:
            return True
        return bool(self.ledger_exists and self.ledger_exists(evidence_id))

    @property
    def task(self) -> m.Task | None:
        key = self.inv.task_key
        return self.mission.tasks.get(key) if key else None

    def must_ac_ids(self) -> list[str]:
        if self.mission.spec is not None:
            return [a.id for a in self.mission.spec.acceptance_criteria if a.priority == "must"]
        return [s.ac.id for s in self.mission.acs if s.ac.priority == "must"]

    def all_ac_ids(self) -> list[str]:
        if self.mission.spec is not None:
            return [a.id for a in self.mission.spec.acceptance_criteria]
        return [s.ac.id for s in self.mission.acs]


Validator = Callable[[LLMOutput, ValidationContext], Awaitable[list[str]]]
VALIDATORS: dict[str, Validator] = {}


def _register(fn: Callable[[Any, ValidationContext], Awaitable[list[str]]]) -> Validator:
    VALIDATORS[fn.__name__.removeprefix("v_")] = fn
    return fn


def _skip(name: str, why: str) -> list[str]:
    log.debug("validator %s skipped: %s", name, why)
    return []


def _walk_strings(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _walk_strings(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            out += _walk_strings(v)
    return out


# ---------------------------------------------------------------------------------------------------
# validators
# ---------------------------------------------------------------------------------------------------


@_register
async def v_paths_exist(out: m.RepoBrief, ctx: ValidationContext) -> list[str]:
    """RepoBrief.relevant_files must exist in the workspace."""
    if ctx.path_exists is None:
        return _skip("paths_exist", "no workspace")
    errs: list[str] = []
    for rf in out.relevant_files:
        if not await ctx.path_exists(norm_path(rf.path)):
            errs.append(f"relevant_files: {rf.path!r} does not exist in the workspace")
    return errs


@_register
async def v_evidence_exists(out: LLMOutput, ctx: ValidationContext) -> list[str]:
    """Every ``E-xxxx`` id anywhere in the output must exist in the evidence ledger."""
    ids: list[str] = []
    for s in _walk_strings(out.model_dump(mode="json")):
        ids += _EVIDENCE_RE.findall(s)
    missing = sorted({i for i in ids if not ctx.evidence_exists(i)})
    return [f"evidence id {i} does not exist in the ledger; cite only ids returned by tools" for i in missing]


@_register
async def v_ac_ids_sequential(out: m.MissionSpec, ctx: ValidationContext) -> list[str]:
    """Acceptance criteria must be AC-1..AC-n with no gaps or duplicates."""
    ids = [a.id for a in out.acceptance_criteria]
    errs: list[str] = []
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errs.append(f"duplicate acceptance criterion ids: {dupes}")
    expected = [f"AC-{n}" for n in range(1, len(ids) + 1)]
    if not dupes and ids != expected:
        errs.append(
            f"acceptance criteria ids must be exactly {expected[0]}..{expected[-1]} in order; got {ids}"
        )
    return errs


@_register
async def v_plan_covers_all_must_acs(out: m.Plan, ctx: ValidationContext) -> list[str]:
    """Every must-priority AC must be referenced by at least one task."""
    refs = {r for t in out.tasks for r in t.acceptance_refs}
    missing = [a for a in ctx.must_ac_ids() if a not in refs]
    return [f"must-priority {a} is not referenced by any task's acceptance_refs" for a in missing]


@_register
async def v_plan_paths_plausible(out: m.Plan, ctx: ValidationContext) -> list[str]:
    """``files_to_touch`` must exist, or at least have a parent directory that exists."""
    if ctx.path_exists is None:
        return _skip("plan_paths_plausible", "no workspace")
    errs: list[str] = []
    for t in out.tasks:
        for f in t.files_to_touch:
            p = norm_path(f)
            if await ctx.path_exists(p):
                continue
            parent = p.rsplit("/", 1)[0] if "/" in p else "."
            if not await ctx.path_exists(parent):
                errs.append(f"{t.key}: {f!r} does not exist and neither does its parent directory {parent!r}")
    return errs


@_register
async def v_revision_has_reason(out: m.Plan, ctx: ValidationContext) -> list[str]:
    """A plan that revises an earlier one must say why (cite finding/evidence ids)."""
    if ctx.mission.plans and not (out.revised_because or "").strip():
        return ["this is a plan revision: revised_because is required (cite finding or evidence ids)"]
    return []


def _dossier(ctx: ValidationContext) -> DecisionDossier | None:
    raw = ctx.inv.extra_context.get("dossier")
    if isinstance(raw, DecisionDossier):
        return raw
    if isinstance(raw, dict):
        try:
            return DecisionDossier.model_validate(raw)
        except ValueError:
            return None
    return None


@_register
async def v_action_is_legal(out: m.Decision, ctx: ValidationContext) -> list[str]:
    """The chosen action (and target) must be in the dossier's legal action set."""
    dossier = _dossier(ctx)
    if dossier is None:
        return _skip("action_is_legal", "no dossier in extra_context")
    for la in dossier.legal_actions:
        if la.action == out.action and (la.target is None or la.target == out.target):
            return []
    legal = ", ".join(f"{la.action.value}({la.target or '-'})" for la in dossier.legal_actions)
    return [f"action {out.action.value} target={out.target!r} is not legal now; legal actions: {legal}"]


@_register
async def v_no_repeat_failed_strategy(out: m.Decision, ctx: ValidationContext) -> list[str]:
    """RETRY_SAME_AGENT is illegal when the task's latest fingerprint has already been seen twice or more."""
    if out.action != Action.RETRY_SAME_AGENT:
        return []
    key = out.target or ctx.inv.task_key
    attempts: list[m.Attempt] = []
    if key and key in ctx.mission.tasks:
        attempts = ctx.mission.tasks[key].attempts
    else:
        dossier = _dossier(ctx)
        if dossier is not None and key in dossier.task_histories:
            attempts = dossier.task_histories[key]
    latest = next((a.fingerprints for a in reversed(attempts) if a.fingerprints), [])
    seen = [fp for a in attempts for fp in a.fingerprints]
    repeated = sorted({fp for fp in latest if seen.count(fp) >= 2})
    return [
        f"RETRY_SAME_AGENT repeats failure fingerprint {fp} already seen {seen.count(fp)} times for {key}; "
        "choose a different action (REASSIGN, ESCALATE_MODEL, TOURNAMENT, INVESTIGATE, REPLAN...)"
        for fp in repeated
    ]


@_register
async def v_acceptance_files_are_tests_only(out: m.AcceptanceSuite, ctx: ValidationContext) -> list[str]:
    """The sentinel may only create or modify test files."""
    errs = [f"suite path {t.path!r} is not a test file" for t in out.tests if not is_test_file(t.path)]
    if ctx.diff_names is not None:
        errs += [
            f"changed file {p!r} is not a test file" for p in await ctx.diff_names() if not is_test_file(p)
        ]
    else:
        log.debug("acceptance_files_are_tests_only: diff check skipped (no workspace)")
    return errs


@_register
async def v_every_must_ac_has_test(out: m.AcceptanceSuite, ctx: ValidationContext) -> list[str]:
    """Every must-priority AC needs at least one named acceptance test."""
    covered = {t.ac_id for t in out.tests if t.test_names}
    return [f"must-priority {a} has no acceptance test" for a in ctx.must_ac_ids() if a not in covered]


@_register
async def v_tests_collect(out: m.AcceptanceSuite, ctx: ValidationContext) -> list[str]:
    """The authored test files must at least be collectable by the test runner."""
    if ctx.collect_tests is None:
        return _skip("tests_collect", "no collector")
    paths = sorted({norm_path(t.path) for t in out.tests})
    if await ctx.collect_tests(paths):
        return []
    return [f"test collection failed for {paths}; fix syntax/import errors in the test files"]


@_register
async def v_fingerprints_match_runs(out: m.TriageReport, ctx: ValidationContext) -> list[str]:
    """Triage items must reference fingerprints that exist in the latest TestRun."""
    if not ctx.mission.test_runs:
        return _skip("fingerprints_match_runs", "no test runs")
    known = {c.fingerprint for c in ctx.mission.test_runs[-1].cases if c.fingerprint}
    return [
        f"triage item {i.nodeid}: fingerprint {i.fingerprint!r} is not in the latest test run"
        for i in out.items
        if i.fingerprint not in known
    ]


@_register
async def v_verdict_covers_all_acs(out: m.VerifierVerdict, ctx: ValidationContext) -> list[str]:
    """Exactly the mission's ACs must be judged: none missing, none invented, none twice."""
    got = [v.ac_id for v in out.per_ac]
    want = ctx.all_ac_ids()
    errs = [f"no verdict for {a}" for a in want if a not in got]
    errs += [f"verdict for unknown {a}" for a in sorted(set(got) - set(want))]
    errs += [f"duplicate verdict for {a}" for a in sorted({a for a in got if got.count(a) > 1})]
    return errs


@_register
async def v_pass_requires_execution_evidence(out: m.VerifierVerdict, ctx: ValidationContext) -> list[str]:
    """A PASS needs a passed check backed by existing test/probe/property/differential evidence."""
    errs: list[str] = []
    for v in out.per_ac:
        if v.verdict != "PASS":
            continue
        ok = False
        for chk in v.checks:
            if not chk.passed:
                continue
            for eid in chk.evidence_ids:
                ev = ctx.mission.evidence.get(eid)
                if ev is not None:
                    ok = ok or ev.kind in _EXECUTION_EVIDENCE
                elif ctx.evidence_exists(eid):
                    log.debug("evidence %s exists in ledger but its kind is unknown; accepted", eid)
                    ok = True
        if not ok:
            errs.append(
                f"{v.ac_id}: PASS needs a passed check with execution evidence "
                "(test run, probe, property or differential); static claims are not enough"
            )
    return errs


@_register
async def v_files_changed_matches_diff(out: m.ChangeReport, ctx: ValidationContext) -> list[str]:
    """``files_changed`` must equal the real set of changed files."""
    if ctx.diff_names is None:
        return _skip("files_changed_matches_diff", "no workspace")
    actual = set(await ctx.diff_names())
    claimed = {norm_path(p) for p in out.files_changed}
    errs: list[str] = []
    if claimed - actual:
        errs.append(f"files_changed lists files not in the diff: {sorted(claimed - actual)}")
    if actual - claimed:
        errs.append(f"files_changed omits files that are in the diff: {sorted(actual - claimed)}")
    return errs


@_register
async def v_within_file_locks(out: m.ChangeReport, ctx: ValidationContext) -> list[str]:
    """The diff may only touch the task's files (plus test files)."""
    task = ctx.task
    if ctx.diff_names is None or task is None:
        return _skip("within_file_locks", "no workspace or no task")
    locks = [norm_path(p).rstrip("/") for p in task.files_to_touch]
    errs: list[str] = []
    for p in await ctx.diff_names():
        if is_test_file(p) or any(p == lk or p.startswith(lk + "/") for lk in locks):
            continue
        errs.append(
            f"{p!r} is outside this task's files_to_touch {task.files_to_touch}; ask Shogun to widen scope"
        )
    return errs


@_register
async def v_rework_states_difference(out: m.ChangeReport, ctx: ValidationContext) -> list[str]:
    """From the second attempt on, the agent must say how its hypothesis differs from earlier ones."""
    if (ctx.inv.attempt or 1) > 1 and not (out.differs_from_previous or "").strip():
        return [
            "differs_from_previous is required on rework: state how this hypothesis differs from failed ones"
        ]
    return []


@_register
async def v_winner_passed_gates(out: m.TournamentResult, ctx: ValidationContext) -> list[str]:
    """The tournament winner must be a candidate whose gates passed."""
    raw = ctx.inv.extra_context.get("candidate_scores")
    if not raw:
        return _skip("winner_passed_gates", "no candidate_scores in extra_context")
    scores = [s if isinstance(s, m.CandidateScore) else m.CandidateScore.model_validate(s) for s in raw]
    by_name = {s.candidate: s for s in scores}
    win = by_name.get(out.winner)
    if win is None:
        return [f"winner {out.winner!r} is not a candidate; candidates: {sorted(by_name)}"]
    if not win.gates_passed:
        return [f"winner {out.winner} failed gates: {win.gate_failures}; pick a gate-passing candidate"]
    return []


@_register
async def v_unproven_blockers_downgraded(out: m.ReviewReport, ctx: ValidationContext) -> list[str]:
    """Blocker/major findings must be proven with evidence; otherwise they must be downgraded to minor."""
    return [
        f"{f.location}: {f.severity} finding must have proven=true and evidence_ids; "
        "downgrade it to minor if you cannot demonstrate it"
        for f in out.findings
        if f.severity in ("blocker", "major") and not (f.proven and f.evidence_ids)
    ]


def _parse_location(loc: str) -> tuple[str, int, int] | None:
    mt = _LOCATION_RE.match(loc.strip())
    if mt is None:
        return None
    start = int(mt.group("start"))
    return norm_path(mt.group("path")), start, int(mt.group("end") or start)


@_register
async def v_introduced_flag_matches_diff(out: m.SecurityReport, ctx: ValidationContext) -> list[str]:
    """``introduced_by_change`` must be true iff the finding's location is inside a changed hunk."""
    if ctx.hunk_paths is None:
        return _skip("introduced_flag_matches_diff", "no hunk source")
    hunks = [h for h in (_parse_location(x) for x in await ctx.hunk_paths()) if h is not None]
    errs: list[str] = []
    for f in out.findings:
        loc = _parse_location(f.location)
        if loc is None:
            path, lo, hi = norm_path(f.location.split(":", 1)[0]), 0, 10**9
        else:
            path, lo, hi = loc
        inside = any(hp == path and hs <= hi and lo <= he for hp, hs, he in hunks)
        if inside != f.introduced_by_change:
            errs.append(
                f"{f.location}: introduced_by_change={f.introduced_by_change} but the location "
                f"{'is' if inside else 'is not'} inside the changed hunks"
            )
    return errs


def _self_check() -> None:
    needed = {name for spec in modes.REGISTRY.values() for name in spec.validators}
    missing = needed - set(VALIDATORS)
    if missing:
        raise AssertionError(f"validators referenced in modes.py but not registered: {sorted(missing)}")


_self_check()
