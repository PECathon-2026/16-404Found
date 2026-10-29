"""The mission orchestrator (docs/04, docs/11 sections 9 and 13).

``Orchestrator.run`` drives one mission from CREATED to a terminal state by choosing which cognitive
mode runs next. It is deterministic glue: every judgement call is an LLM mode (``shogun.decide`` ...),
every bound on autonomy is code (``guards``), every step is an event (``Blackboard.emit``).

Flow: INTEL -> RECON -> ANALYZING -> (CLARIFYING) -> PLANNING (+premortem) -> (plan gate) ->
AUTHORING_ACCEPTANCE -> EXECUTING <-> TESTING <-> DECIDING -> CHECKING -> AWAITING_APPLY ->
APPLYING -> REPORTING -> terminal.

Counters the event projection does not carry (fix cycles, tournaments, wall clock) are kept here and
mirrored into BUDGET_WARNING / DECISION payloads; see the handoff note for the contract request.
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from devpilot.config import Settings
from devpilot.core.events import Event, EventType
from devpilot.core.models import (
    AcceptanceSuite,
    ACStatus,
    Action,
    AgentMessage,
    Attempt,
    BudgetState,
    ChangeReport,
    ClarifyingOption,
    Decision,
    DecisionDossier,
    Evidence,
    EvidenceKind,
    Finding,
    HumanDecision,
    HumanPrompt,
    InvestigationReport,
    LegalAction,
    MessageType,
    Mission,
    MissionSpec,
    MissionStatus,
    ModelTier,
    Plan,
    PlanRecord,
    PreMortem,
    ProgressVector,
    Reflection,
    RepoBrief,
    ReviewLens,
    ReviewReport,
    ScoredVerdict,
    SecurityReport,
    Severity,
    Submission,
    Task,
    TaskStatus,
    TestClass,
    TestRun,
    TriageItem,
    TriageReport,
    VerifierVerdict,
)
from devpilot.core.ports import (
    AgentRuntime,
    Blackboard,
    DeltaDebugger,
    HumanChannel,
    ModeInvocation,
    RepoIntelService,
    TestRunner,
    Workspaces,
)
from devpilot.engine.errors import ModeError
from devpilot.engine.validators import parse_diff_names
from devpilot.orchestrator import ac_rules, dossier, guards, progress, scheduler
from devpilot.orchestrator.transitions import assert_legal

log = logging.getLogger(__name__)

M = MissionStatus
T = TaskStatus
O = TypeVar("O", bound=BaseModel)  # noqa: E741 - short alias for "output type"

MAX_PHASES = 400  # defence in depth: a hard cap on phase iterations, independent of every budget
MAX_CLARIFY_ROUNDS = 2
MAX_PLAN_EDITS = 2
MAX_STALE_RECHECKS = 3
_EVIDENCE_PATTERN = re.compile(r"^E-\d{4,}$")
_BLOCKING_SEVERITIES = ("blocker", "major")


class _Fatal(Exception):
    """Unrecoverable orchestration failure: the mission ends FAILED."""


@dataclass(slots=True)
class _Work:
    """One Samurai invocation to run in the next EXECUTING phase."""

    task_key: str
    mode_id: str
    agent_id: str
    tier: ModelTier | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Trigger:
    """A reason to call ``shogun.decide`` about one task."""

    task_key: str
    kind: str
    event: Event
    summary: str
    allowed: frozenset[Action] | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    watches: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _Stop:
    """Why the mission is heading to REPORTING. ``status=None`` means "derive from the evidence"."""

    status: MissionStatus | None
    reason: str


@dataclass(slots=True)
class _Failure:
    """One blocking result of the CHECKING gate, to be routed to a task."""

    kind: str  # Finding.kind
    severity: Severity
    summary: str
    payload: dict[str, Any]
    task_key: str
    evidence_ids: list[str]
    source_agent: str
    source_mode: str
    fingerprint: str | None = None


class Orchestrator:
    """Drives one mission. See the module docstring; ``run()`` is the only public entry point."""

    def __init__(
        self,
        blackboard: Blackboard,
        runtime: AgentRuntime,
        workspaces: Workspaces,
        tests: TestRunner,
        human: HumanChannel,
        settings: Settings,
        *,
        repo_intel: RepoIntelService | None = None,
        ddmin: DeltaDebugger | None = None,
        tournament: Callable[..., Awaitable[str]] | None = None,
        report_writer: Callable[[Mission], Awaitable[None]] | None = None,
        reflect: bool = True,
    ) -> None:
        self.bb = blackboard
        self.runtime = runtime
        self.workspaces = workspaces
        self.tests = tests
        self.human = human
        self.settings = settings
        self.repo_intel = repo_intel
        self.ddmin = ddmin
        self.tournament = tournament
        self.report_writer = report_writer
        self.reflect = reflect
        # --- orchestrator-side state ---
        self._stop: _Stop | None = None
        self._applied = False
        self._fix_cycles = 0
        self._tournaments = 0
        self._samurai_n = 0
        self._cycle_used = False
        self._pending_work: list[_Work] = []
        self._triggers: list[_Trigger] = []
        self._last_action: dict[str, Action] = {}
        self._fired_watches: set[int] = set()
        self._ids: defaultdict[str, int] = defaultdict(int)
        self._spawned: set[str] = set()
        self._last_reviews: list[ReviewReport] = []
        self._last_security: SecurityReport | None = None
        self._t0 = 0.0
        self._wall_base = 0.0  # wall clock already spent before this run (reload)
        self._human_wait = 0.0
        self._timeout: asyncio.Timeout | None = None

    # ------------------------------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------------------------------

    @property
    def mission(self) -> Mission:
        return self.bb.mission

    async def run(self) -> MissionStatus:
        """Drive the mission to a terminal state and return it.

        ``CancelledError`` ends the mission ABORTED (after a shielded REPORTING) and is re-raised.
        """
        if self.mission.status.terminal:
            return self.mission.status
        loop = asyncio.get_running_loop()
        self._t0 = loop.time()
        # Counters live here but are mirrored into BUDGET_WARNING; re-seed them so a reload keeps them.
        b = self.mission.budget
        self._fix_cycles = max(self._fix_cycles, b.fix_cycles)
        self._tournaments = max(self._tournaments, b.tournaments)
        self._wall_base = b.wall_clock_s
        limit = max(1.0, float(b.limits.max_wall_clock_s) - self._wall_base)
        try:
            try:
                async with asyncio.timeout(limit) as cm:
                    self._timeout = cm
                    await self._drive()
            except TimeoutError:
                if self._timeout is None or not self._timeout.expired():
                    raise
                await self._emit(
                    EventType.BUDGET_EXCEEDED,
                    {"wall_clock_s": self._elapsed(), "limit": limit},
                    summary=f"wall clock of {limit:.0f}s exceeded",
                )
                self._stop = _Stop(M.COMPLETED_PARTIAL, f"wall clock of {limit:.0f}s exceeded")
        except asyncio.CancelledError:
            self._stop = _Stop(M.ABORTED, "mission cancelled")
            await asyncio.shield(self._finish())
            raise
        except _Fatal as exc:
            log.error("mission failed: %s", exc)
            self._stop = _Stop(M.FAILED, str(exc))
        except Exception as exc:
            log.exception("orchestrator crashed")
            self._stop = _Stop(M.FAILED, f"orchestrator error: {type(exc).__name__}: {exc}")
        finally:
            self._timeout = None
        return await self._finish()

    # ------------------------------------------------------------------------------------------
    # low-level helpers
    # ------------------------------------------------------------------------------------------

    def _elapsed(self) -> float:
        return self._wall_base + asyncio.get_running_loop().time() - self._t0 - self._human_wait

    def _counters(self) -> guards.GuardCounters:
        return guards.GuardCounters(
            fix_cycles=self._fix_cycles, tournaments=self._tournaments, wall_clock_s=self._elapsed()
        )

    def _budget(self) -> BudgetState:
        return guards.effective_budget(self.mission, self._counters())

    def _next_id(self, prefix: str, taken: Iterable[str]) -> str:
        used = set(taken)
        while True:
            self._ids[prefix] += 1
            cand = f"{prefix}-{self._ids[prefix]:04d}"
            if cand not in used:
                return cand

    async def _emit(
        self,
        type_: EventType,
        payload: dict[str, Any],
        *,
        actor: str = "system",
        task_key: str | None = None,
        mode_id: str | None = None,
        summary: str = "",
    ) -> Event:
        return await self.bb.emit(type_, actor, payload, task_key=task_key, mode_id=mode_id, summary=summary)

    async def _status(self, to: MissionStatus, reason: str) -> None:
        frm = self.mission.status
        if frm == to and to != M.CHECKING:
            return
        assert_legal(frm, to)
        await self._emit(
            EventType.STATE_CHANGED,
            {"from": frm, "to": to, "reason": reason},
            summary=f"{frm.value} -> {to.value}: {reason}",
        )

    async def _task_to(
        self,
        key: str,
        to: TaskStatus,
        *,
        attempt: Attempt | None = None,
        assignee: str | None = None,
        inbox_consumed: list[str] | None = None,
        summary: str = "",
    ) -> Event:
        task = self.mission.tasks[key]
        assert_legal(task.status, to)
        payload: dict[str, Any] = {"task_key": key, "to": to, "from": task.status}
        if assignee is not None:
            payload["assignee"] = assignee
        if attempt is not None:
            payload["attempt"] = attempt
        if inbox_consumed:
            payload["inbox_consumed"] = inbox_consumed
        return await self._emit(
            EventType.TASK_STATE_CHANGED,
            payload,
            task_key=key,
            summary=summary or f"{key}: {task.status.value} -> {to.value}",
        )

    async def _ensure_rework(self, key: str) -> None:
        """Bring a task to REWORK from any state a decision can find it in."""
        task = self.mission.tasks[key]
        if task.status in (T.DONE, T.BLOCKED, T.TESTING, T.ESCALATED):
            await self._task_to(key, T.REWORK, summary=f"{key}: reopened for rework")

    def _sub_for(
        self, mode_id: str, *, agent_id: str | None = None, task_key: str | None = None
    ) -> Submission | None:
        for sub in reversed(list(self.mission.submissions.values())):
            if sub.mode_id != mode_id:
                continue
            if agent_id is not None and sub.agent_id != agent_id:
                continue
            if task_key is not None and sub.task_key != task_key:
                continue
            return sub
        return None

    async def _invoke(self, inv: ModeInvocation, cls: type[O]) -> O:
        out = await self.runtime.invoke(inv)
        if isinstance(out, cls):
            return out
        return cls.model_validate(out.model_dump())

    async def _invoke_critical(self, inv: ModeInvocation, cls: type[O]) -> O:
        """Invoke a mode the mission cannot continue without: one retry, then the mission FAILS."""
        last: ModeError | None = None
        for _ in range(2):
            try:
                return await self._invoke(inv, cls)
            except ModeError as exc:
                last = exc
                log.warning("critical mode %s failed: %s", inv.mode_id, exc)
        raise _Fatal(f"{inv.mode_id} failed twice: {last}")

    async def _ask_human(self, prompt: HumanPrompt) -> HumanDecision:
        """Emit the prompt, wait (the wait does not count against the wall clock), emit the answer."""
        await self._emit(
            EventType.HUMAN_PROMPT, {"prompt": prompt}, summary=f"{prompt.gate} gate: {prompt.title}"
        )
        loop = asyncio.get_running_loop()
        started = loop.time()
        when = self._timeout.when() if self._timeout is not None else None
        if self._timeout is not None:
            self._timeout.reschedule(None)  # the wall clock is paused while a human thinks
        try:
            decision = await self.human.ask(prompt)
        finally:
            waited = loop.time() - started
            self._human_wait += waited
            if self._timeout is not None and when is not None:
                self._timeout.reschedule(when + waited)
        if decision.prompt_id != prompt.id:
            decision = decision.model_copy(update={"prompt_id": prompt.id})
        await self._emit(
            EventType.HUMAN_DECISION,
            {"decision": decision},
            actor="human",
            summary=f"human answered {prompt.gate}: {decision.choice or (decision.free_text or '')[:60]}",
        )
        return decision

    def _pseudo_event(self, summary: str) -> Event:
        """A non-persisted Event naming a decision trigger that has no event of its own."""
        return Event(
            seq=self.mission.last_seq,
            mission_id=self.mission.id,
            type=EventType.STATE_CHANGED,
            actor="system",
            summary=summary,
        )

    @staticmethod
    def _is_cancel(d: HumanDecision) -> bool:
        return d.choice in ("cancel", "abort") or (not d.choice and not (d.free_text or "").strip())

    # ------------------------------------------------------------------------------------------
    # test runs, evidence and watch conditions
    # ------------------------------------------------------------------------------------------

    @staticmethod
    def _effective_green(run: TestRun) -> bool:
        """Green unless something *blocking* failed: pre-existing and flaky failures do not count."""
        if run.verdict == "green":
            return True
        if run.verdict == "error" or not run.cases:
            return False
        if run.regressions:
            return False
        return not any(
            c.outcome in progress.FAILING
            and c.classification not in (TestClass.STILL_FAILING, TestClass.FLAKY)
            for c in run.cases
        )

    def _acs_supported_by(self, run: TestRun) -> list[str]:
        """ACs whose acceptance tests all passed in ``run`` (all ACs when no suite mapping exists)."""
        acs = [a.ac for a in self.mission.acs]
        suite_sub = self._sub_for("sentinel.author_acceptance")
        passed = {c.nodeid for c in run.cases if c.outcome.value == "passed"}
        if suite_sub is None:
            return [a.id for a in acs]
        suite = AcceptanceSuite.model_validate(suite_sub.payload)
        out: list[str] = []
        for ac in acs:
            tests = [t for t in suite.tests if t.ac_id == ac.id]
            names = [n for t in tests for n in t.test_names]
            if not names:
                if ac.preserves_existing_behaviour and run.scope in ("full", "baseline"):
                    out.append(ac.id)
                continue
            if all(any(n == p or p.endswith(f"::{n}") or n in p for p in passed) for n in names):
                out.append(ac.id)
        return out

    async def _record_test_run(self, run: TestRun, *, watch: bool) -> Event:
        """Emit TEST_RUN; derive the Evidence record from the run when the runner did not ledger one."""
        payload: dict[str, Any] = {"test_run": run}
        if run.evidence_id not in self.mission.evidence:
            sha = await self.workspaces.tree_sha(run.workspace_ref)
            green = self._effective_green(run)
            payload["evidence"] = Evidence(
                id=run.evidence_id,
                kind=EvidenceKind.TEST_RUN,
                tool="test.run",
                agent_id="system",
                workspace_ref=run.workspace_ref,
                workspace_sha=sha,
                exit_code=0 if green else 1,
                summary=f"{run.scope} tests {run.verdict}: {run.totals}",
                log_path=f"evidence/{run.evidence_id}",
                sha256=hashlib.sha256(run.model_dump_json().encode()).hexdigest(),
                structured={"totals": run.totals, "scope": run.scope},
                ac_ids=self._acs_supported_by(run) if green else [],
            )
        ev = await self._emit(
            EventType.TEST_RUN,
            payload,
            summary=f"{run.scope} tests {run.verdict}: {run.totals} ({run.evidence_id})",
        )
        if watch:
            await self._check_watches(run=run)
        return ev

    async def _check_watches(self, *, run: TestRun | None = None, finding: Finding | None = None) -> None:
        """Evaluate premortem watch conditions; each fires at most once and becomes a decision point."""
        for i, w in enumerate(self.mission.watch_conditions):
            if i in self._fired_watches:
                continue
            detail: str | None = None
            if w.trigger == "test_fails" and run is not None:
                hit = [c.nodeid for c in progress.failing_cases(run) if fnmatch.fnmatch(c.nodeid, w.pattern)]
                detail = f"failing: {', '.join(hit)}" if hit else None
            elif w.trigger == "file_touched" and run is not None:
                names = parse_diff_names(await self.workspaces.diff())
                hit = [n for n in names if fnmatch.fnmatch(n, w.pattern)]
                detail = f"touched: {', '.join(hit)}" if hit else None
            elif w.trigger == "finding_category" and finding is not None:
                cat = str(finding.payload.get("category", ""))
                if w.pattern in (cat, finding.kind):
                    detail = f"finding {finding.id} category {cat or finding.kind}"
            elif w.trigger == "budget_ratio":
                try:
                    threshold = float(w.pattern)
                except ValueError:
                    continue
                ratio = self._budget().ratio()
                if ratio >= threshold:
                    detail = f"budget ratio {ratio:.2f} >= {threshold}"
            if detail is None:
                continue
            self._fired_watches.add(i)
            info = {
                "description": w.description,
                "trigger": w.trigger,
                "pattern": w.pattern,
                "suggested_response": w.response,
                "detail": detail,
            }
            key = (finding.routed_to if finding else None) or self._default_owner()
            ev = await self._emit(
                EventType.WATCH_TRIGGERED, info, task_key=key, summary=f"watch triggered: {w.description}"
            )
            if key is not None:
                self._triggers.append(
                    _Trigger(key, "watch", ev, f"watch condition: {w.description} ({detail})", watches=[info])
                )

    # ------------------------------------------------------------------------------------------
    # task / owner helpers
    # ------------------------------------------------------------------------------------------

    def _live_tasks(self) -> list[Task]:
        return [t for t in self.mission.tasks.values() if t.status != T.CANCELLED]

    def _default_owner(self, likely: str | None = None) -> str | None:
        tasks = self.mission.tasks
        if likely is not None and likely in tasks and tasks[likely].status != T.CANCELLED:
            return likely
        active = [
            t for t in self._live_tasks() if t.status in (T.TESTING, T.IN_PROGRESS, T.SUBMITTED, T.REWORK)
        ]
        if len(active) == 1:
            return active[0].key
        pool = active or self._live_tasks()
        return pool[0].key if pool else None

    def _owner_for_ac(self, ac_id: str) -> str | None:
        for t in self._live_tasks():
            if ac_id in t.acceptance_refs:
                return t.key
        return self._default_owner()

    def _owner_for_location(self, location: str) -> str | None:
        path = location.split(":", 1)[0].replace("\\", "/")
        for t in self._live_tasks():
            if any(
                path == f or path.startswith(f.rstrip("/") + "/") or fnmatch.fnmatch(path, f)
                for f in t.files_to_touch
            ):
                return t.key
        return self._default_owner()

    def _new_agent(self) -> str:
        self._samurai_n += 1
        return f"samurai#{self._samurai_n}"

    def _tournament_available(self) -> bool:
        profile = self.settings.profiles.get(self.settings.active_profile)
        return self.tournament is not None and (profile is None or profile.allow_tournaments)

    async def _route(
        self,
        *,
        kind: str,
        severity: Severity,
        summary: str,
        payload: dict[str, Any],
        task_key: str,
        evidence_ids: list[str],
        source_agent: str,
        source_mode: str,
        subject: str,
        body: str,
        msg_type: MessageType = MessageType.FINDING,
        watch: bool = True,
    ) -> Finding:
        """Record a Finding and deliver it to the owning task's inbox (the feedback loop)."""
        m = self.mission
        finding = Finding(
            id=self._next_id("F", m.findings),
            source_agent=source_agent,
            source_mode=source_mode,
            kind=kind,
            severity=severity,
            summary=summary,
            payload=payload,
            routed_to=task_key,
            evidence_ids=evidence_ids,
        )
        await self._emit(
            EventType.FINDING,
            {"finding": finding},
            actor=source_agent,
            task_key=task_key,
            mode_id=source_mode,
            summary=f"{kind} finding {finding.id} -> {task_key}: {summary[:120]}",
        )
        msg = AgentMessage(
            id=self._next_id("MSG", m.messages),
            sender=source_agent,
            to=f"task:{task_key}",
            type=msg_type,
            subject=subject,
            body=body,
            refs=[finding.id],
            evidence_ids=evidence_ids,
        )
        await self._emit(
            EventType.MESSAGE_SENT,
            {"message": msg},
            actor=source_agent,
            task_key=task_key,
            summary=f"{source_agent} -> task:{task_key}: {subject}",
        )
        if watch:
            await self._check_watches(finding=finding)
        return finding

    async def _message(
        self,
        sender: str,
        to: str,
        type_: MessageType,
        subject: str,
        body: str,
        *,
        task_key: str | None = None,
        refs: list[str] | None = None,
    ) -> None:
        msg = AgentMessage(
            id=self._next_id("MSG", self.mission.messages),
            sender=sender,
            to=to,
            type=type_,
            subject=subject,
            body=body,
            refs=refs or [],
        )
        await self._emit(
            EventType.MESSAGE_SENT,
            {"message": msg},
            actor=sender,
            task_key=task_key,
            summary=f"{sender} -> {to}: {subject}",
        )

    async def _set_findings(self, task_keys: Iterable[str] | None, kinds: set[str], status: str) -> None:
        """Re-emit open findings with a new status (the log stays the single source of truth)."""
        keys = set(task_keys) if task_keys is not None else None
        for f in list(self.mission.findings.values()):
            if f.status != "open" or f.kind not in kinds:
                continue
            if keys is not None and f.routed_to not in keys:
                continue
            await self._emit(
                EventType.FINDING,
                {"finding": f.model_copy(update={"status": status})},
                actor=f.source_agent,
                task_key=f.routed_to,
                summary=f"finding {f.id} {status}",
            )

    # ------------------------------------------------------------------------------------------
    # driver
    # ------------------------------------------------------------------------------------------

    async def _drive(self) -> None:
        await self._phase_intel()
        if await self._phase_analyze() is None:
            return
        await self._phase_plan()
        if self._stop:
            return
        await self._phase_acceptance()
        await self._main_loop()

    async def _main_loop(self) -> None:
        phase = M.EXECUTING
        for _ in range(MAX_PHASES):
            if self._stop or phase == M.REPORTING:
                return
            if self._elapsed() >= self.mission.budget.limits.max_wall_clock_s:
                self._stop = _Stop(M.COMPLETED_PARTIAL, "wall clock exhausted")
                return
            if phase == M.EXECUTING:
                phase = await self._executing()
            elif phase == M.TESTING:
                phase = await self._testing()
            elif phase == M.DECIDING:
                phase = await self._deciding()
            elif phase == M.CHECKING:
                phase = await self._checking()
            elif phase == M.AWAITING_APPLY:
                phase = await self._awaiting_apply()
            elif phase == M.APPLYING:
                phase = await self._applying()
            else:  # pragma: no cover - phases are produced by this class only
                raise _Fatal(f"no handler for phase {phase}")
        self._stop = _Stop(M.COMPLETED_PARTIAL, f"phase cap of {MAX_PHASES} reached")
        await self._emit(
            EventType.BUDGET_EXCEEDED, {"phase_cap": MAX_PHASES}, summary="orchestrator phase cap reached"
        )

    # ------------------------------------------------------------------------------------------
    # INTEL, RECON, ANALYZING, CLARIFYING
    # ------------------------------------------------------------------------------------------

    async def _phase_intel(self) -> None:
        await self._status(M.INTEL, "deterministic repository intelligence and baseline tests")
        if self.repo_intel is not None:
            try:
                ws = await self.workspaces.path("main")
                intel = await self.repo_intel.build(ws, self.mission.request)
                await self._emit(EventType.INTEL_READY, {"intel": intel}, summary="repo intelligence ready")
            except Exception as exc:
                log.warning("repo intelligence failed, continuing without it: %s", exc)
                await self._emit(
                    EventType.TOOL_UNAVAILABLE,
                    {"tool": "repo_intel", "error": str(exc)},
                    summary=f"repo intelligence unavailable: {exc}",
                )
        run = await self.tests.run("baseline")
        await self._record_test_run(run, watch=False)

    async def _phase_analyze(self) -> MissionSpec | None:
        await self._status(M.RECON, "scout interprets the repository")
        await self._invoke_critical(ModeInvocation("scout.recon", "scout"), RepoBrief)
        await self._status(M.ANALYZING, "shogun converts the request into acceptance criteria")
        spec = await self._invoke_critical(ModeInvocation("shogun.analyze", "shogun"), MissionSpec)
        rounds = 0
        while spec.ambiguity.level.value == "high" and self.settings.gates.clarification:
            if rounds >= MAX_CLARIFY_ROUNDS:
                log.warning("ambiguity still high after %d clarifications; proceeding", rounds)
                break
            answer = await self._clarify(spec)
            if answer is None:
                self._stop = _Stop(M.ABORTED, "human cancelled at the clarification gate")
                return None
            await self._status(M.ANALYZING, "re-analysing with the human's clarification")
            inv = ModeInvocation("shogun.analyze", "shogun", extra_context={"clarification": answer})
            spec = await self._invoke_critical(inv, MissionSpec)
            rounds += 1
        return spec

    async def _clarify(self, spec: MissionSpec) -> str | None:
        await self._status(M.CLARIFYING, "ambiguity is high; asking the human")
        amb = spec.ambiguity
        body = [amb.question or "The request is ambiguous.", ""]
        body += [f"- **{o.key}** {o.label}: {o.consequence}" for o in amb.options]
        if amb.default_option:
            body.append(f"\nDefault if you have no preference: `{amb.default_option}`.")
        prompt = HumanPrompt(
            id=self._next_id("P", self.mission.prompts),
            gate="clarification",
            title="Clarification needed",
            body_md="\n".join(body),
            options=[o.model_copy() for o in amb.options],
        )
        decision = await self._ask_human(prompt)
        if self._is_cancel(decision):
            return None
        parts: list[str] = []
        chosen = next((o for o in amb.options if o.key == decision.choice), None)
        if chosen is not None:
            parts.append(f"{chosen.key}: {chosen.label} ({chosen.consequence})")
        elif decision.choice:
            parts.append(decision.choice)
        if decision.free_text and decision.free_text.strip():
            parts.append(decision.free_text.strip())
        return "; ".join(parts)

    # ------------------------------------------------------------------------------------------
    # PLANNING (+ premortem, plan gate), AUTHORING_ACCEPTANCE
    # ------------------------------------------------------------------------------------------

    async def _adopt_plan(self, plan: Plan, premortem: PreMortem | None, why: str) -> PlanRecord:
        m = self.mission
        version = len(m.plans) + 1
        record = PlanRecord(id=f"plan-v{version}", version=version, plan=plan, premortem=premortem)
        tasks = {
            d.key: Task(
                id=f"{m.id}:{d.key}:v{version}",
                key=d.key,
                title=d.title,
                description=d.description,
                acceptance_refs=d.acceptance_refs,
                files_to_touch=d.files_to_touch,
                depends_on=d.depends_on,
                may_edit_tests=d.may_edit_tests,
                risk=d.risk,
                strategy_hint=d.strategy_hint,
                plan_version=version,
            )
            for d in plan.tasks
        }
        await self._emit(
            EventType.PLAN_ADOPTED,
            {"plan_record": record, "tasks": tasks},
            summary=f"plan v{version} adopted ({len(tasks)} tasks): {why}",
        )
        for key, t in tasks.items():
            if not t.depends_on:
                await self._task_to(key, T.READY, summary=f"{key}: no dependencies, READY")
        return record

    async def _phase_plan(self) -> None:
        await self._status(M.PLANNING, "shogun decomposes the mission")
        plan = await self._invoke_critical(ModeInvocation("shogun.plan", "shogun"), Plan)
        premortem: PreMortem | None = None
        profile = self.settings.profiles.get(self.settings.active_profile)
        if profile is None or profile.allow_premortem:
            try:
                premortem = await self._invoke(ModeInvocation("shogun.premortem", "shogun"), PreMortem)
            except ModeError as exc:
                log.warning("premortem failed, adopting the plan as is: %s", exc)
        if premortem is not None and premortem.plan_amendments is not None:
            plan = premortem.plan_amendments
        await self._adopt_plan(
            plan,
            premortem,
            "premortem amendments adopted" if premortem and premortem.plan_amendments else "initial plan",
        )
        if not self.settings.gates.plan:
            return
        for edits in range(MAX_PLAN_EDITS + 1):
            await self._status(M.AWAITING_PLAN_APPROVAL, "plan approval gate is enabled")
            plan_now = self.mission.plans[-1].plan
            lines = [
                f"- **{t.key}** {t.title} (risk {t.risk.value}; files: {', '.join(t.files_to_touch) or '-'})"
                for t in plan_now.tasks
            ]
            prompt = HumanPrompt(
                id=self._next_id("P", self.mission.prompts),
                gate="plan",
                title=f"Approve plan v{self.mission.plans[-1].version}?",
                body_md=plan_now.rationale + "\n\n" + "\n".join(lines),
                options=[
                    ClarifyingOption(
                        key="approve", label="Approve", consequence="Start implementing this plan"
                    ),
                    ClarifyingOption(key="cancel", label="Cancel", consequence="Abort the mission"),
                ],
            )
            decision = await self._ask_human(prompt)
            if decision.choice == "approve":
                return
            text = (decision.free_text or "").strip()
            if (
                decision.choice in ("cancel", "abort")
                or (not decision.choice and not text)
                or edits >= MAX_PLAN_EDITS
            ):
                self._stop = _Stop(M.ABORTED, "human did not approve the plan")
                return
            await self._status(M.PLANNING, "human asked for plan changes")
            inv = ModeInvocation("shogun.plan", "shogun", extra_context={"human_feedback": text})
            revised = await self._invoke_critical(inv, Plan)
            await self._adopt_plan(revised, None, "revised after human feedback")

    async def _phase_acceptance(self) -> None:
        await self._status(M.AUTHORING_ACCEPTANCE, "sentinel writes public acceptance tests before any code")
        try:
            suite = await self._invoke(
                ModeInvocation("sentinel.author_acceptance", "sentinel"), AcceptanceSuite
            )
        except ModeError as exc:
            log.warning("acceptance authoring failed; continuing without a public suite: %s", exc)
            return
        run = await self.tests.run("acceptance", selectors=[t.path for t in suite.tests])
        await self._record_test_run(run, watch=False)  # red is expected here

    # ------------------------------------------------------------------------------------------
    # EXECUTING
    # ------------------------------------------------------------------------------------------

    async def _executing(self) -> MissionStatus:
        m = self.mission
        works, self._pending_work = self._pending_work, []
        if not works:
            ready = scheduler.ready_tasks(m)
            if not ready:
                return await self._no_runnable()
            chosen = scheduler.batch(ready, m.budget.limits.max_parallel_samurai)
            for t in chosen:
                if t.status == T.PENDING:
                    await self._task_to(t.key, T.READY, summary=f"{t.key}: dependencies done, READY")
            works = [_Work(t.key, "samurai.implement", self._new_agent()) for t in chosen]
        await self._status(M.EXECUTING, f"running {', '.join(w.task_key for w in works)}")
        remaining = works
        while remaining:
            by_key = {w.task_key: w for w in remaining}
            wave = scheduler.batch([m.tasks[k] for k in by_key], m.budget.limits.max_parallel_samurai)
            wave_works = [by_key[t.key] for t in wave]
            await asyncio.gather(*(self._run_work(w) for w in wave_works))
            done = {w.task_key for w in wave_works}
            remaining = [w for w in remaining if w.task_key not in done]
        submitted = [t.key for t in self._live_tasks() if t.status == T.SUBMITTED]
        if not submitted:
            return M.DECIDING
        sha = await self.workspaces.checkpoint(f"after {','.join(submitted)}")
        await self._emit(
            EventType.CHECKPOINT,
            {"sha": sha, "label": f"after {','.join(submitted)}", "progress": None},
            summary=f"checkpoint {sha[:8]}",
        )
        return M.TESTING

    async def _no_runnable(self) -> MissionStatus:
        """EXECUTING was entered with nothing to run."""
        live = self._live_tasks()
        if live and all(t.status == T.DONE for t in live):
            return M.CHECKING
        stuck = next((t for t in live if t.status != T.DONE), None)
        if stuck is None:
            self._stop = _Stop(M.COMPLETED_PARTIAL, "the plan has no runnable tasks")
            return M.REPORTING
        trigger_event = self._pseudo_event(f"no runnable task; {stuck.key} is {stuck.status.value}")
        self._triggers.append(
            _Trigger(
                stuck.key,
                "deadlock",
                trigger_event,
                trigger_event.summary,
                allowed=frozenset({Action.REPLAN, Action.ASK_HUMAN, Action.STOP_PARTIAL}),
            )
        )
        return M.DECIDING

    async def _run_work(self, w: _Work) -> None:
        """One Samurai attempt: spawn, record the attempt, invoke, record the outcome."""
        key = w.task_key
        task = self.mission.tasks[key]
        if task.status in (T.DONE, T.BLOCKED, T.TESTING, T.ESCALATED):
            await self._ensure_rework(key)
        n = len(task.attempts) + 1
        if w.agent_id not in self._spawned:
            self._spawned.add(w.agent_id)
            await self._emit(
                EventType.AGENT_SPAWNED,
                {"agent_id": w.agent_id, "role": "samurai", "task": key, "mode": w.mode_id},
                actor="system",
                task_key=key,
                summary=f"spawned {w.agent_id} for {key}",
            )
        attempt = Attempt(n=n, mode_id=w.mode_id, agent_id=w.agent_id, model="", outcome="pending")
        consumed = list(self.mission.tasks[key].inbox)
        await self._task_to(
            key,
            T.IN_PROGRESS,
            attempt=attempt,
            assignee=w.agent_id,
            summary=f"{key}: attempt {n} by {w.agent_id} ({w.mode_id})",
        )
        inv = ModeInvocation(
            w.mode_id, w.agent_id, task_key=key, attempt=n, extra_context=dict(w.extra), tier_override=w.tier
        )
        try:
            report = await self._invoke(inv, ChangeReport)
        except ModeError as exc:
            ev = await self._task_to(
                key,
                T.BLOCKED,
                attempt=attempt.model_copy(update={"outcome": "blocked"}),
                inbox_consumed=consumed,
                summary=f"{key}: {w.mode_id} failed: {exc.reason}",
            )
            self._triggers.append(_Trigger(key, "mode_error", ev, f"{w.mode_id} failed: {exc.reason}"))
            return
        sub = self._sub_for(w.mode_id, agent_id=w.agent_id, task_key=key)
        done = attempt.model_copy(
            update={
                "model": sub.model if sub else "",
                "submission_id": sub.id if sub else None,
                "hypothesis": report.hypothesis,
                "outcome": "blocked" if report.status == "blocked" else "pending",
            }
        )
        if report.status == "blocked":
            ev = await self._task_to(
                key,
                T.BLOCKED,
                attempt=done,
                inbox_consumed=consumed,
                summary=f"{key}: {w.agent_id} reports blocked: {'; '.join(report.blockers)[:160]}",
            )
            self._triggers.append(
                _Trigger(
                    key, "blocked", ev, f"{key} blocked: {'; '.join(report.blockers) or report.approach}"
                )
            )
        else:
            await self._task_to(
                key,
                T.SUBMITTED,
                attempt=done,
                inbox_consumed=consumed,
                summary=f"{key}: {w.agent_id} submitted attempt {n} ({report.status})",
            )

    # ------------------------------------------------------------------------------------------
    # TESTING
    # ------------------------------------------------------------------------------------------

    async def _targeted_selectors(self) -> list[str]:
        if self.repo_intel is None:
            return []
        sels: set[str] = set()
        try:
            hunks = await self.workspaces.hunks()
        except Exception as exc:
            log.warning("hunks unavailable for targeted tests: %s", exc)
            hunks = []
        for h in hunks:
            start, count = h["new_start"], h["new_len"]
            sels.update(self.repo_intel.tests_covering(h["path"], range(start, start + max(count, 1))))
        if not hunks:
            for t in self._live_tasks():
                if t.status == T.TESTING:
                    for f in t.files_to_touch:
                        sels.update(self.repo_intel.tests_covering(f, ()))
        return sorted(sels)

    def _record_progress_attempt(
        self, key: str, fps: list[str], tree_sha: str, outcome: str, checkpoint: str | None
    ) -> Attempt | None:
        task = self.mission.tasks[key]
        if not task.attempts:
            return None
        pv = progress.progress_vector(self.mission, key, tree_sha=tree_sha)
        return task.attempts[-1].model_copy(
            update={
                "fingerprints": sorted(set(fps)),
                "progress": pv,
                "outcome": outcome,
                "checkpoint_sha": checkpoint,
            }
        )

    async def _testing(self) -> MissionStatus:
        await self._status(M.TESTING, "running tests on the checkpointed tree")
        submitted = [t.key for t in self._live_tasks() if t.status == T.SUBMITTED]
        for key in submitted:
            await self._task_to(key, T.TESTING)
        run: TestRun | None = None
        trigger_event: Event | None = None
        selectors = await self._targeted_selectors()
        if selectors:
            targeted = await self.tests.run("targeted", selectors=selectors)
            ev = await self._record_test_run(targeted, watch=True)
            if not self._effective_green(targeted):
                run, trigger_event = targeted, ev
        if run is None:
            run = await self.tests.run("full")
            trigger_event = await self._record_test_run(run, watch=True)
        assert trigger_event is not None
        tree = await self.workspaces.tree_sha()
        if self._effective_green(run):
            return await self._after_green(submitted, tree)
        return await self._after_red(run, trigger_event, submitted, tree)

    async def _after_green(self, submitted: list[str], tree: str) -> MissionStatus:
        m = self.mission
        cp = await self._checkpoint_if_best(tree, "green")
        for key in submitted:
            att = self._record_progress_attempt(key, [], tree, "green", cp)
            await self._task_to(key, T.DONE, attempt=att, summary=f"{key}: tests green, DONE")
        await self._set_findings(submitted, {"triage"}, "addressed")
        if self._triggers:
            return M.DECIDING
        if scheduler.ready_tasks(m):
            return M.EXECUTING
        live = self._live_tasks()
        if live and all(t.status == T.DONE for t in live):
            return M.CHECKING
        return M.EXECUTING  # _executing reports deadlock

    async def _checkpoint_if_best(self, tree: str, label: str) -> str | None:
        """Checkpoint (git commit + CHECKPOINT event) when this state is the best progress so far."""
        m = self.mission
        keys = [t.key for t in self._live_tasks() if t.attempts]
        if not keys:
            return None
        pv = progress.progress_vector(m, keys[0], tree_sha=tree)
        recorded = [ProgressVector.model_validate(c["progress"]) for c in m.checkpoints if c.get("progress")]
        if recorded and progress.badness(pv) >= min(progress.badness(p) for p in recorded):
            return None
        sha = await self.workspaces.checkpoint(f"best-so-far ({label})")
        await self._emit(
            EventType.CHECKPOINT,
            {"sha": sha, "label": f"best-so-far ({label})", "progress": pv},
            summary=f"best-so-far checkpoint {sha[:8]}",
        )
        return sha

    async def _after_red(
        self, run: TestRun, trigger_event: Event, submitted: list[str], tree: str
    ) -> MissionStatus:
        owners: dict[str, list[str]] = {}  # task key -> fingerprints
        report = await self._triage(run, submitted)
        if report is not None:
            for item in report.items:
                key = self._default_owner(item.likely_owner_task)
                if key is None:
                    continue
                await self._route_triage(item, key, run)
                owners.setdefault(key, []).append(item.fingerprint)
        if not owners:
            key = self._default_owner()
            if key is None:
                self._stop = _Stop(M.COMPLETED_PARTIAL, "tests are red and no task owns the failure")
                return M.REPORTING
            fps = sorted({c.fingerprint for c in progress.failing_cases(run) if c.fingerprint})
            failing = [c.nodeid for c in progress.failing_cases(run)]
            await self._route(
                kind="triage",
                severity=Severity.HIGH,
                summary=f"{len(failing)} test(s) failing: {', '.join(failing[:5])}",
                payload={"fallback": True, "category": "regression", "nodeids": failing, "fingerprints": fps},
                task_key=key,
                evidence_ids=[run.evidence_id],
                source_agent="system",
                source_mode="orchestrator.fallback_triage",
                subject="Tests are red (no triage available)",
                body="Triage was unavailable. Failing tests:\n" + "\n".join(f"- {n}" for n in failing),
            )
            owners[key] = fps
        cp = await self._checkpoint_if_best(tree, "red")
        for key in submitted:
            fps = owners.get(key, [])
            att = self._record_progress_attempt(key, fps, tree, "red" if key in owners else "pending", cp)
            if key in owners:
                await self._task_to(key, T.REWORK, attempt=att, summary=f"{key}: tests red, REWORK")
        for key in owners:
            if key not in submitted:
                await self._ensure_rework(key)
            self._triggers.append(
                _Trigger(
                    key,
                    "test_red",
                    trigger_event,
                    f"{run.scope} tests {run.verdict} ({run.evidence_id}); {key} fingerprints {owners[key]}",
                )
            )
        return M.DECIDING

    async def _triage(self, run: TestRun, submitted: list[str]) -> TriageReport | None:
        extra: dict[str, Any] = {}
        if self.ddmin is not None and run.regressions:
            try:
                res = await self.ddmin.isolate(run.regressions)
                extra["ddmin"] = res
                await self._emit(
                    EventType.DELTA_DEBUG,
                    {"result": res, "failing": run.regressions},
                    summary="delta debugging isolated culprit hunks",
                )
            except Exception as exc:
                log.warning("ddmin failed: %s", exc)
        try:
            return await self._invoke(
                ModeInvocation("sentinel.triage", "sentinel", extra_context=extra), TriageReport
            )
        except ModeError as exc:
            log.warning("triage failed: %s", exc)
            return None

    async def _route_triage(self, item: TriageItem, key: str, run: TestRun) -> None:
        sev = Severity.HIGH if item.category == "regression" else Severity.MEDIUM
        hyps = "\n".join(
            f"{h.rank}. {h.statement} [{h.status}] - experiment: {h.experiment}" for h in item.hypotheses
        )
        evidence = list(
            dict.fromkeys([run.evidence_id, *(e for h in item.hypotheses for e in h.evidence_ids)])
        )
        body = (
            f"{item.nodeid} fails ({item.error_type}); fingerprint {item.fingerprint}; category {item.category}; "
            f"confidence {item.confidence:.2f}.\n"
            f"Implicated: {', '.join(item.implicated_locations) or '-'}\n"
            f"Fix direction: {item.fix_direction}\nHypotheses:\n{hyps}"
        )
        await self._route(
            kind="triage",
            severity=sev,
            summary=f"{item.nodeid}: {item.fix_direction}",
            payload=item.model_dump(mode="json"),
            task_key=key,
            evidence_ids=evidence,
            source_agent="sentinel",
            source_mode="sentinel.triage",
            subject=f"Triage: {item.nodeid} ({item.fingerprint})",
            body=body,
        )

    # ------------------------------------------------------------------------------------------
    # DECIDING
    # ------------------------------------------------------------------------------------------

    def _merge_triggers(self) -> list[_Trigger]:
        merged: dict[str, _Trigger] = {}
        for trig in self._triggers:
            cur = merged.get(trig.task_key)
            if cur is None:
                merged[trig.task_key] = trig
                continue
            if cur.kind == "watch" and trig.kind != "watch":
                trig.watches = cur.watches + trig.watches
                merged[trig.task_key] = trig
            else:
                cur.watches += trig.watches
                if trig.allowed is not None:
                    cur.allowed = trig.allowed if cur.allowed is None else cur.allowed & trig.allowed
        self._triggers = []
        return list(merged.values())

    def _legal_for(self, trig: _Trigger) -> list[LegalAction]:
        legal = guards.legal_actions(
            self.mission,
            trig.task_key,
            tournament_available=self._tournament_available(),
            counters=self._counters(),
        )
        if trig.allowed is not None:
            legal = [la for la in legal if la.action in trig.allowed]
            if not legal:
                legal = [
                    LegalAction(
                        action=Action.STOP_PARTIAL,
                        est_tokens=0,
                        est_seconds=0,
                        note="no other action is legal for this trigger",
                    )
                ]
        return legal

    def _cited_evidence(self) -> str:
        for run in reversed(self.mission.test_runs):
            if _EVIDENCE_PATTERN.match(run.evidence_id):
                return run.evidence_id
        return "E-0000"

    async def _decide(
        self, trig: _Trigger, legal: list[LegalAction], d: DecisionDossier
    ) -> tuple[Decision, str]:
        """Ask ``shogun.decide`` (or decide deterministically when only one action is legal)."""
        only = legal[0].action if len(legal) == 1 else None
        decision: Decision | None = None
        why = ""
        if only is None:
            extra: dict[str, Any] = {"dossier": d.model_dump(mode="json"), **trig.extra}
            if trig.watches:
                extra["watch_triggered"] = trig.watches
            inv = ModeInvocation("shogun.decide", "shogun", task_key=trig.task_key, extra_context=extra)
            try:
                decision = await self._invoke(inv, Decision)
            except ModeError as exc:
                why = f"shogun.decide failed ({exc.reason}); orchestrator decided"
        else:
            why = f"only {only.value} is legal here; orchestrator decided without an LLM call"
        if decision is not None:
            sub = self._sub_for("shogun.decide", agent_id="shogun", task_key=trig.task_key)
            assert sub is not None, "runtime must have recorded the decision submission"
            return decision, sub.id
        action = only or (
            Action.ASK_HUMAN if any(la.action == Action.ASK_HUMAN for la in legal) else legal[0].action
        )
        decision = Decision(
            action=action,
            target=trig.task_key,
            justification=f"{why}. Trigger: {trig.summary}",
            cited_evidence=[self._cited_evidence()],
            expected_outcome="n/a (deterministic)",
            confidence=1.0,
            fallback_if_fails=Action.STOP_PARTIAL,
        )
        sub = Submission(
            id=self._next_id("S-sys", self.mission.submissions),
            mode_id="shogun.decide",
            agent_id="system",
            model="deterministic",
            task_key=trig.task_key,
            output_type="Decision",
            payload=decision.model_dump(mode="json"),
        )
        await self._emit(
            EventType.SUBMISSION,
            {"submission": sub},
            task_key=trig.task_key,
            mode_id="shogun.decide",
            summary=f"deterministic decision {action.value}: {why}",
        )
        return decision, sub.id

    async def _deciding(self) -> MissionStatus:
        m = self.mission
        triggers = self._merge_triggers()
        triggers = [
            t for t in triggers if t.task_key in m.tasks and m.tasks[t.task_key].status != T.CANCELLED
        ]
        if not triggers:
            return self._after_decide_phase()
        await self._status(M.DECIDING, "; ".join(t.summary for t in triggers)[:300])
        self._cycle_used = False
        for trig in triggers:
            if self._stop:
                break
            if trig.task_key not in m.tasks or m.tasks[trig.task_key].status == T.CANCELLED:
                continue  # a replan earlier in this pass removed it
            await self._decide_one(trig)
        if self._cycle_used:
            self._fix_cycles += 1
            await self._emit(
                EventType.BUDGET_WARNING,
                {
                    "fix_cycles": self._fix_cycles,
                    "max_fix_cycles": m.budget.limits.max_fix_cycles,
                    "tournaments": self._tournaments,
                    "replans": max(len(m.plans) - 1, 0),
                    "wall_clock_s": round(self._elapsed(), 3),
                },
                summary=f"fix cycle {self._fix_cycles} of {m.budget.limits.max_fix_cycles}",
            )
        if self._stop:
            return M.REPORTING
        return self._after_decide_phase()

    def _after_decide_phase(self) -> MissionStatus:
        m = self.mission
        if self._stop:
            return M.REPORTING
        if self._pending_work or scheduler.ready_tasks(m) or m.status == M.PLANNING:
            return M.EXECUTING
        if any(t.status == T.SUBMITTED for t in self._live_tasks()):
            return M.TESTING
        if self._triggers:
            return M.DECIDING
        live = self._live_tasks()
        if live and all(t.status == T.DONE for t in live):
            return M.CHECKING
        return M.EXECUTING

    async def _decide_one(self, trig: _Trigger) -> None:
        m = self.mission
        key = trig.task_key
        legal = self._legal_for(trig)
        d = dossier.build_dossier(m, trig.event, key, legal, budget=self._budget())
        decision, sub_id = await self._decide(trig, legal, d)
        final, reason = guards.override(
            decision, m, key, tournament_available=self._tournament_available(), counters=self._counters()
        )
        if final not in {la.action for la in legal}:
            reason = reason or f"trigger_restriction: {final.value} is not allowed after {trig.kind}"
            final = (
                legal[0].action
                if len(legal) == 1
                else next(
                    (a for a in guards.PREFERENCE if a in {la.action for la in legal}), Action.STOP_PARTIAL
                )
            )
        if final == Action.ASK_HUMAN and not self.settings.gates.escalation:
            final, reason = Action.STOP_PARTIAL, "gates.escalation disabled: cannot ask a human"
        if reason:
            await self._emit(
                EventType.GUARD_OVERRIDE,
                {
                    "task": key,
                    "proposed": decision.action,
                    "final": final,
                    "reason": reason,
                    "guard": reason.split(":", 1)[0],
                },
                task_key=key,
                summary=f"guard override on {key}: {decision.action.value} -> {final.value} ({reason})",
            )
        await self._emit(
            EventType.DECISION,
            {
                "submission_id": sub_id,
                "final_action": final,
                "overridden_by_guard": reason,
                "proposed_action": decision.action,
                "task_key": key,
                "trigger_event_seq": trig.event.seq,
                "fix_cycles": self._fix_cycles,
            },
            task_key=key,
            mode_id="shogun.decide",
            summary=f"decision for {key}: {final.value}" + (f" (guard: {reason})" if reason else ""),
        )
        prev = self._last_action.get(key)
        forbade_retry = (
            reason is not None and decision.action == Action.RETRY_SAME_AGENT and final != decision.action
        )
        if (prev is not None and prev != final) or forbade_retry:
            await self._emit(
                EventType.STRATEGY_CHANGED,
                {
                    "task": key,
                    "from": prev,
                    "to": final,
                    "reason": reason
                    or f"decision changed from {prev.value if prev else '-'} to {final.value}",
                },
                task_key=key,
                summary=f"strategy changed on {key}: {prev.value if prev else '-'} -> {final.value}",
            )
        self._last_action[key] = final
        target = (
            decision.target
            if decision.target in m.tasks and m.tasks[decision.target].status != T.CANCELLED
            else key
        )
        await self._execute(final, decision, trig, target)

    async def _directive(self, task_key: str, action: Action, decision: Decision) -> dict[str, Any]:
        """Deliver the Shogun's guidance to the task inbox; return extra context for the next attempt."""
        body = f"{decision.justification}\nExpected: {decision.expected_outcome}"
        if decision.strategy_hints:
            body += "\nGuidance:\n" + "\n".join(f"- {h}" for h in decision.strategy_hints)
        await self._message(
            "shogun",
            f"task:{task_key}",
            MessageType.INFO,
            f"Decision: {action.value}",
            body,
            task_key=task_key,
        )
        extra: dict[str, Any] = {}
        if decision.strategy_hints:
            extra["strategy_hint"] = "; ".join(decision.strategy_hints)
        return extra

    def _queue(
        self,
        task_key: str,
        mode_id: str,
        agent_id: str,
        *,
        tier: ModelTier | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._pending_work = [w for w in self._pending_work if w.task_key != task_key]
        self._pending_work.append(_Work(task_key, mode_id, agent_id, tier, extra or {}))
        self._cycle_used = True

    async def _execute(self, action: Action, decision: Decision, trig: _Trigger, key: str) -> None:
        m = self.mission
        task = m.tasks[key]
        if trig.kind == "human_changes":
            text = str(trig.extra.get("human_feedback", ""))
            if text and action in (
                Action.RETRY_SAME_AGENT,
                Action.REASSIGN,
                Action.ESCALATE_MODEL,
                Action.INVESTIGATE,
                Action.ROLLBACK,
                Action.TOURNAMENT,
            ):
                await self._message(
                    "human",
                    f"task:{key}",
                    MessageType.REQUEST,
                    "Changes requested at the apply gate",
                    text,
                    task_key=key,
                )
        if action == Action.RETRY_SAME_AGENT:
            extra = await self._directive(key, action, decision)
            self._queue(key, "samurai.rework", task.assignee or self._new_agent(), extra=extra)
        elif action == Action.REASSIGN:
            extra = await self._directive(key, action, decision)
            self._queue(key, "samurai.implement", self._new_agent(), extra=extra)
        elif action == Action.ESCALATE_MODEL:
            extra = await self._directive(key, action, decision)
            await self._emit(
                EventType.MODEL_ESCALATED,
                {"task": key, "to_tier": ModelTier.FRONTIER, "reason": "decision ESCALATE_MODEL"},
                task_key=key,
                summary=f"{key}: next attempt on the frontier tier",
            )
            self._queue(
                key,
                "samurai.rework",
                task.assignee or self._new_agent(),
                tier=ModelTier.FRONTIER,
                extra=extra,
            )
        elif action == Action.INVESTIGATE:
            await self._investigate(decision, key)
        elif action == Action.REPLAN:
            await self._replan(decision.justification, key)
        elif action == Action.TOURNAMENT:
            await self._run_tournament(decision, key)
        elif action == Action.ROLLBACK:
            await self._rollback(decision, key)
        elif action == Action.ASK_HUMAN:
            await self._escalate(decision, key)
        elif action == Action.ABORT:
            self._stop = _Stop(M.ABORTED, f"abort decided: {decision.justification[:200]}")
        else:  # STOP_PARTIAL (CONTINUE is never legal)
            self._stop = _Stop(None, f"stopped on decision: {decision.justification[:200]}")

    async def _investigate(self, decision: Decision, key: str) -> None:
        question = f"{decision.justification} (task {key})"[:600]
        inv = ModeInvocation("scout.investigate", "scout", task_key=key, extra_context={"question": question})
        try:
            report = await self._invoke(inv, InvestigationReport)
        except ModeError as exc:
            log.warning("investigation failed: %s", exc)
            extra = await self._directive(key, Action.INVESTIGATE, decision)
            self._queue(
                key, "samurai.rework", self.mission.tasks[key].assignee or self._new_agent(), extra=extra
            )
            return
        body = f"{report.answer}\nFindings:\n" + "\n".join(f"- {f}" for f in report.findings)
        await self._route(
            kind="investigation",
            severity=Severity.INFO,
            summary=report.answer[:200],
            payload=report.model_dump(mode="json"),
            task_key=key,
            evidence_ids=list(report.evidence_ids),
            source_agent="scout",
            source_mode="scout.investigate",
            subject=f"Investigation: {report.question[:80]}",
            body=body,
            msg_type=MessageType.RESPONSE,
        )
        replans = len(self.mission.plans) - 1
        if report.recommends_replan and replans < self.mission.budget.limits.max_replans:
            await self._replan(f"investigation recommends a replan: {report.answer}", key)
            return
        extra = await self._directive(key, Action.INVESTIGATE, decision)
        self._queue(key, "samurai.rework", self.mission.tasks[key].assignee or self._new_agent(), extra=extra)

    async def _replan(self, reason: str, key: str) -> None:
        m = self.mission
        open_ids = [f.id for f in m.findings.values() if f.status == "open"]
        await self._status(M.PLANNING, f"replan: {reason[:160]}")
        extra = {"revised_because": reason, "open_findings": open_ids}
        plan = await self._invoke_critical(ModeInvocation("shogun.plan", "shogun", extra_context=extra), Plan)
        old = [t.key for t in m.tasks.values() if t.status != T.DONE]
        await self._adopt_plan(plan, None, f"replan: {reason[:120]}")
        await self._set_findings(
            old, {"triage", "review", "security", "verifier", "investigation"}, "superseded"
        )
        self._pending_work = [
            w
            for w in self._pending_work
            if w.task_key in m.tasks and m.tasks[w.task_key].status != T.CANCELLED
        ]
        self._cycle_used = True

    async def _run_tournament(self, decision: Decision, key: str) -> None:
        assert self.tournament is not None  # guarded by legal_actions
        self._tournaments += 1
        self._cycle_used = True
        task = self.mission.tasks[key]
        await self._ensure_rework(key)
        n = len(task.attempts) + 1
        await self._task_to(
            key, T.TOURNAMENT, summary=f"{key}: tournament with {len(decision.strategy_hints)} strategies"
        )
        try:
            winner = await self.tournament(key, list(decision.strategy_hints))
        except Exception as exc:
            log.warning("tournament failed: %s", exc)
            att = Attempt(n=n, mode_id="samurai.explore", agent_id="tournament", model="", outcome="blocked")
            ev = await self._task_to(key, T.BLOCKED, attempt=att, summary=f"{key}: tournament failed: {exc}")
            self._triggers.append(_Trigger(key, "mode_error", ev, f"tournament failed: {exc}"))
            return
        att = Attempt(
            n=n,
            mode_id="samurai.explore",
            agent_id=f"tournament:{winner}",
            model="",
            hypothesis=f"tournament winner {winner}",
            outcome="pending",
        )
        await self._task_to(
            key,
            T.SUBMITTED,
            attempt=att,
            assignee=f"tournament:{winner}",
            summary=f"{key}: tournament winner {winner} adopted",
        )

    async def _rollback(self, decision: Decision, key: str) -> None:
        m = self.mission
        task = m.tasks[key]
        history = guards.progress_history(task)
        target = guards.best_checkpoint(m, history[-1] if history else None)
        extra = await self._directive(key, Action.ROLLBACK, decision)
        if target is not None:
            await self.workspaces.rollback(str(target["sha"]))
            await self._emit(
                EventType.ROLLBACK,
                {
                    "sha": target["sha"],
                    "label": target.get("label"),
                    "task": key,
                    "reason": decision.justification[:200],
                },
                task_key=key,
                summary=f"rolled back to checkpoint {str(target['sha'])[:8]}",
            )
        else:
            log.warning("ROLLBACK chosen but no better checkpoint exists; reworking in place")
        self._queue(key, "samurai.rework", task.assignee or self._new_agent(), extra=extra)

    async def _escalate(self, decision: Decision, key: str) -> None:
        m = self.mission
        task = m.tasks[key]
        await self._ensure_rework(key)
        if m.tasks[key].status == T.REWORK:
            await self._task_to(key, T.ESCALATED, summary=f"{key}: escalated to a human")
        body = (
            f"Task **{key}** ({task.title}) needs a human.\n\n{decision.question_for_human or decision.justification}\n\n"
            f"Attempts: {len(task.attempts)}; fix cycles used: {self._fix_cycles}."
        )
        prompt = HumanPrompt(
            id=self._next_id("P", m.prompts),
            gate="escalation",
            title=f"Guidance needed on {key}",
            body_md=body,
            options=[
                ClarifyingOption(
                    key="guidance",
                    label="Provide guidance",
                    consequence="The task is reworked with your guidance",
                ),
                ClarifyingOption(
                    key="accept_partial",
                    label="Accept partial result",
                    consequence="Stop and report what is verified",
                ),
                ClarifyingOption(key="abort", label="Abort", consequence="Abort the mission"),
            ],
        )
        ans = await self._ask_human(prompt)
        text = (ans.free_text or "").strip()
        if ans.choice == "abort":
            self._stop = _Stop(M.ABORTED, "human aborted at the escalation gate")
        elif ans.choice == "accept_partial" or (not ans.choice and not text):
            self._stop = _Stop(None, "human accepted a partial result")
        else:
            if text:
                await self._message(
                    "human", f"task:{key}", MessageType.INFO, "Human guidance", text, task_key=key
                )
            self._queue(key, "samurai.rework", self.mission.tasks[key].assignee or self._new_agent())

    # ------------------------------------------------------------------------------------------
    # CHECKING
    # ------------------------------------------------------------------------------------------

    async def _try(self, inv: ModeInvocation, cls: type[O]) -> tuple[O | None, str | None]:
        err = ""
        for attempt in range(2):  # one retry: checks are idempotent
            try:
                return await self._invoke(inv, cls), None
            except ModeError as exc:
                err = f"{inv.mode_id}: {exc.reason}"
                log.warning("check failed (attempt %d): %s", attempt + 1, err)
        return None, err

    async def _checking(self) -> MissionStatus:
        m = self.mission
        await self._status(M.CHECKING, "tests are green; verifier, reviewers and security inspect the diff")
        sha = ""
        for _ in range(MAX_STALE_RECHECKS):
            sha = await self.workspaces.tree_sha()
            verify_r, review_rs, security_r = await asyncio.gather(
                self._try(ModeInvocation("verifier.verify", "verifier"), VerifierVerdict),
                asyncio.gather(
                    *(
                        self._try(
                            ModeInvocation(
                                "reviewer.review", f"reviewer-{lens.value}", extra_context={"lens": lens}
                            ),
                            ReviewReport,
                        )
                        for lens in ReviewLens
                    )
                ),
                self._try(ModeInvocation("security.inspect", "security"), SecurityReport),
            )
            sha_after = await self.workspaces.tree_sha()
            if sha_after == sha:
                break
            await self._status(
                M.CHECKING, f"stale verdict guard: tree changed {sha[:8]} -> {sha_after[:8]}; re-checking"
            )
        else:
            return await self._check_error(f"the tree kept changing during {MAX_STALE_RECHECKS} checks")
        verdict, verr = verify_r
        security, serr = security_r
        errors = [e for e in [verr, serr, *(r[1] for r in review_rs)] if e]
        reviews = [r[0] for r in review_rs if r[0] is not None]
        self._last_reviews, self._last_security = reviews, security
        verdict_event: Event | None = None
        if verdict is not None:
            scored = ScoredVerdict(
                id=self._next_id("V", [v.id for v in m.verdicts]),
                diff_sha=sha,
                verdict=verdict,
                confidence_by_ac={av.ac_id: ac_rules.confidence(av) for av in verdict.per_ac},
            )
            verdict_event = await self._emit(
                EventType.VERDICT,
                {"verdict": scored},
                actor="system",
                summary=f"verifier {verdict.overall} on tree {sha[:8]}",
            )
            for state in list(m.acs):
                new = ac_rules.ac_status(state.ac, m, sha)
                if new != state.status:
                    await self._emit(
                        EventType.AC_STATUS_CHANGED,
                        {
                            "ac_id": state.ac.id,
                            "status": new,
                            "evidence_ids": ac_rules.supporting_evidence_ids(m, state.ac.id, sha),
                            "confidence": scored.confidence_by_ac.get(state.ac.id),
                        },
                        summary=f"{state.ac.id}: {state.status.value} -> {new.value}",
                    )
        failures = self._gate_failures(verdict, reviews, security)
        if errors:
            return await self._check_error("; ".join(errors), verdict_event, failures, sha)
        if not failures:
            await self._set_findings(None, {"review", "security", "verifier", "investigation"}, "addressed")
            return M.AWAITING_APPLY
        await self._route_failures(failures, verdict_event, sha)
        return M.DECIDING

    def _gate_failures(
        self, verdict: VerifierVerdict | None, reviews: list[ReviewReport], security: SecurityReport | None
    ) -> list[_Failure]:
        out: list[_Failure] = []
        if verdict is not None:
            for av in verdict.per_ac:
                if av.verdict != "FAIL":
                    continue
                out.append(
                    _Failure(
                        "verifier",
                        Severity.BLOCKER,
                        f"{av.ac_id} FAIL: {av.counterexample or av.reasoning}"[:300],
                        av.model_dump(mode="json"),
                        self._owner_for_ac(av.ac_id) or "",
                        list(dict.fromkeys(e for c in av.checks for e in c.evidence_ids)),
                        "verifier",
                        "verifier.verify",
                        fingerprint=progress.verifier_fingerprint(av),
                    )
                )
            if not verdict.test_integrity_ok:
                out.append(
                    _Failure(
                        "verifier",
                        Severity.BLOCKER,
                        f"test integrity violated: {verdict.integrity_notes}"[:300],
                        {"integrity_notes": verdict.integrity_notes},
                        self._default_owner() or "",
                        [],
                        "verifier",
                        "verifier.verify",
                    )
                )
            if verdict.overall != "ACCEPT" and not any(f.kind == "verifier" for f in out):
                out.append(
                    _Failure(
                        "verifier",
                        Severity.MAJOR,
                        f"verifier verdict {verdict.overall} without a failing AC",
                        verdict.model_dump(mode="json"),
                        self._default_owner() or "",
                        [],
                        "verifier",
                        "verifier.verify",
                    )
                )
        for rep in reviews:
            for f in rep.findings:
                if f.severity in _BLOCKING_SEVERITIES:
                    out.append(
                        _Failure(
                            "review",
                            Severity.BLOCKER if f.severity == "blocker" else Severity.MAJOR,
                            f"[{f.lens.value}] {f.location}: {f.description}"[:300],
                            f.model_dump(mode="json"),
                            self._owner_for_location(f.location) or "",
                            list(f.evidence_ids),
                            f"reviewer-{rep.lens.value}",
                            "reviewer.review",
                        )
                    )
        if security is not None and security.decision == "block":
            blocking = [
                sf
                for sf in security.findings
                if sf.introduced_by_change and sf.severity in ("critical", "high", "medium")
            ]
            for sf in blocking or security.findings:
                out.append(
                    _Failure(
                        "security",
                        Severity(sf.severity),
                        f"{sf.location}: {sf.description}"[:300],
                        sf.model_dump(mode="json"),
                        self._owner_for_location(sf.location) or "",
                        list(sf.evidence_ids),
                        "security",
                        "security.inspect",
                    )
                )
            if not security.findings:
                out.append(
                    _Failure(
                        "security",
                        Severity.HIGH,
                        "security inspection blocked the change",
                        security.model_dump(mode="json"),
                        self._default_owner() or "",
                        [],
                        "security",
                        "security.inspect",
                    )
                )
        return out

    async def _route_failures(self, failures: list[_Failure], verdict_event: Event | None, sha: str) -> None:
        m = self.mission
        by_task: dict[str, list[_Failure]] = defaultdict(list)
        for f in failures:
            key = f.task_key or (self._default_owner() or "")
            if key:
                by_task[key].append(f)
        for key, fs in by_task.items():
            for f in fs:
                payload = dict(f.payload)
                if f.fingerprint:
                    payload["fingerprint"] = f.fingerprint
                await self._route(
                    kind=f.kind,
                    severity=f.severity,
                    summary=f.summary,
                    payload=payload,
                    task_key=key,
                    evidence_ids=f.evidence_ids,
                    source_agent=f.source_agent,
                    source_mode=f.source_mode,
                    subject=f"{f.kind.capitalize()}: {f.summary[:80]}",
                    body=f.summary
                    + (
                        f"\nCounterexample: {f.payload.get('counterexample')}"
                        if f.payload.get("counterexample")
                        else ""
                    ),
                )
            fps = sorted({f.fingerprint for f in fs if f.fingerprint})
            att = None
            task = m.tasks[key]
            if task.attempts:
                pv = progress.progress_vector(m, key, tree_sha=sha)
                att = task.attempts[-1].model_copy(
                    update={
                        "fingerprints": sorted(set(task.attempts[-1].fingerprints) | set(fps)),
                        "progress": pv,
                        "outcome": "rejected",
                    }
                )
            if task.status == T.DONE:
                await self._task_to(key, T.REWORK, attempt=att, summary=f"{key}: rejected by checks, REWORK")
            ev = verdict_event or self._pseudo_event("checks failed")
            self._triggers.append(_Trigger(key, "checks", ev, "; ".join(f.summary for f in fs)[:300]))

    async def _check_error(
        self,
        why: str,
        verdict_event: Event | None = None,
        failures: list[_Failure] | None = None,
        sha: str = "",
    ) -> MissionStatus:
        if failures and verdict_event is not None:
            await self._route_failures(failures, verdict_event, sha)
        key = self._default_owner()
        if key is None:
            self._stop = _Stop(M.COMPLETED_PARTIAL, f"checks could not complete: {why}")
            return M.REPORTING
        ev = self._pseudo_event(f"checks incomplete: {why}"[:300])
        self._triggers.append(
            _Trigger(
                key,
                "check_error",
                ev,
                f"checks incomplete: {why}"[:300],
                allowed=frozenset({Action.ASK_HUMAN, Action.STOP_PARTIAL}),
            )
        )
        return M.DECIDING

    # ------------------------------------------------------------------------------------------
    # AWAITING_APPLY, APPLYING
    # ------------------------------------------------------------------------------------------

    async def _apply_body(self) -> str:
        m = self.mission
        sha = await self.workspaces.tree_sha()
        rows = ["| AC | Status | Confidence |", "|---|---|---|"]
        for a in m.acs:
            conf = f"{a.confidence:.2f}" if a.confidence is not None else "-"
            rows.append(f"| {a.ac.id} {a.ac.then[:60]} | {a.status.value} | {conf} |")
        run = next((r for r in reversed(m.test_runs) if r.scope in ("full", "targeted")), None)
        tests = (
            f"{run.scope}: {run.verdict}; {run.totals}; regressions {len(run.regressions)} ({run.evidence_id})"
            if run
            else "no test run recorded"
        )
        review = (
            ", ".join(
                f"{r.lens.value}: {r.decision} ({len(r.findings)} findings)" for r in self._last_reviews
            )
            or "n/a"
        )
        security = (
            f"{self._last_security.decision} ({len(self._last_security.findings)} findings)"
            if self._last_security
            else "n/a"
        )
        claims: list[str] = []
        for t in m.tasks.values():
            sub = self._sub_for("samurai.rework", task_key=t.key) or self._sub_for(
                "samurai.implement", task_key=t.key
            )
            if sub is not None:
                claims += [str(c) for c in sub.payload.get("claims", [])]
        unverified = [a.ac.id for a in m.acs if a.status != ACStatus.VERIFIED]
        try:
            files = parse_diff_names(await self.workspaces.diff())
        except Exception:
            files = []
        return "\n".join(
            [
                f"**Request:** {m.request}",
                "",
                *rows,
                "",
                f"**Tests:** {tests}",
                f"**Review:** {review}",
                f"**Security:** {security}",
                f"**Unverified ACs:** {', '.join(unverified) or 'none'}",
                f"**Unverified claims:** {len(claims)}" + ("".join(f"\n- {c}" for c in claims)),
                f"**Files:** {', '.join(files) or '-'}",
                f"**Tree:** `{sha}`",
            ]
        )

    async def _awaiting_apply(self) -> MissionStatus:
        m = self.mission
        await self._status(M.AWAITING_APPLY, "all checks passed; mandatory human apply gate")
        prompt = HumanPrompt(
            id=self._next_id("P", m.prompts),
            gate="apply",
            title="Apply the change to the target repository?",
            body_md=await self._apply_body(),
            options=[
                ClarifyingOption(
                    key="approve",
                    label="Approve and apply",
                    consequence="Merges the mission branch into the target repository",
                ),
                ClarifyingOption(
                    key="request_changes",
                    label="Request changes",
                    consequence="Routes your note to the Shogun and keeps working",
                ),
                ClarifyingOption(
                    key="reject", label="Reject", consequence="Nothing is applied; the mission ends partial"
                ),
            ],
            context_refs=[v.id for v in m.verdicts[-1:]],
        )
        ans = await self._ask_human(prompt)
        text = (ans.free_text or "").strip()
        if ans.choice == "approve":
            return M.APPLYING
        if ans.choice == "request_changes" or (not ans.choice and text):
            await self._message(
                "human",
                "shogun",
                MessageType.REQUEST,
                "Changes requested at the apply gate",
                text or "(no details given)",
            )
            key = self._default_owner()
            if key is None:
                self._stop = _Stop(M.COMPLETED_PARTIAL, "changes requested but no task to rework")
                return M.REPORTING
            ev = self._pseudo_event(f"human requested changes: {text[:120]}")
            self._triggers.append(
                _Trigger(
                    key,
                    "human_changes",
                    ev,
                    f"human requested changes: {text[:200]}",
                    extra={"human_feedback": text},
                )
            )
            return M.DECIDING
        self._stop = _Stop(M.COMPLETED_PARTIAL, "human rejected the change at the apply gate")
        return M.REPORTING

    async def _applying(self) -> MissionStatus:
        await self._status(M.APPLYING, "human approved; merging into the target repository")
        try:
            ref = await self.workspaces.apply_to_target()
        except Exception as exc:
            log.warning("apply failed: %s", exc)
            self._stop = _Stop(M.COMPLETED_PARTIAL, f"apply to target failed: {exc}")
            return M.REPORTING
        tree = await self.workspaces.tree_sha()
        await self._emit(
            EventType.APPLIED, {"ref": ref, "tree_sha": tree}, summary=f"applied to target ({ref})"
        )
        self._applied = True
        self._stop = _Stop(None, "change applied after human approval")
        return M.REPORTING

    # ------------------------------------------------------------------------------------------
    # REPORTING
    # ------------------------------------------------------------------------------------------

    def _terminal(self, stop: _Stop) -> MissionStatus:
        """docs/04 section 1 outcome rules. FAILED is reserved for unrecoverable orchestration errors."""
        if stop.status is not None:
            return stop.status
        must = [a for a in self.mission.acs if a.ac.priority == "must"]
        if self._applied and must and all(a.status == ACStatus.VERIFIED for a in must):
            return M.COMPLETED_VERIFIED
        return M.COMPLETED_PARTIAL

    def _digest(self) -> str:
        m = self.mission
        lines = [f"request: {m.request}"]
        lines += [f"AC {a.ac.id}: {a.status.value}" for a in m.acs]
        lines += [f"{t.key} [{t.status.value}] attempts={len(t.attempts)}" for t in m.tasks.values()]
        lines += [
            f"decision by {d.agent_id}: {d.payload.get('action')} - {str(d.payload.get('justification'))[:120]}"
            for d in m.decisions
        ]
        lines += [f"finding {f.id} [{f.kind}/{f.status}]: {f.summary[:100]}" for f in m.findings.values()]
        return "\n".join(lines)

    async def _finish(self) -> MissionStatus:
        stop = self._stop or _Stop(None, "mission ended")
        m = self.mission
        if m.status != M.REPORTING:
            await self._status(M.REPORTING, stop.reason)
        if self.reflect and stop.status not in (M.ABORTED, M.FAILED):
            try:
                await self._invoke(
                    ModeInvocation(
                        "shogun.reflect", "shogun", extra_context={"event_digest": self._digest()}
                    ),
                    Reflection,
                )
            except Exception as exc:  # reflection is best-effort and must never block the report
                log.warning("reflection failed: %s", exc)
        if self.report_writer is not None:
            try:
                await asyncio.shield(self.report_writer(m))
                await self._emit(EventType.REPORT_WRITTEN, {"status": stop.status}, summary="report written")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("report writer failed: %s", exc)
        final = self._terminal(stop)
        await self._status(final, stop.reason)
        await self._emit(
            EventType.MISSION_FINISHED,
            {
                "status": final,
                "reason": stop.reason,
                "applied": self._applied,
                "acs": {a.ac.id: a.status.value for a in m.acs},
                "fix_cycles": self._fix_cycles,
            },
            summary=f"mission finished: {final.value} ({stop.reason})",
        )
        return final
