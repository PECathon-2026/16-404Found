"""Fakes and builders for the orchestrator tests (imported as ``orch_helpers``).

``ScriptedRuntime`` is an ``AgentRuntime`` that returns scripted ``LLMOutput`` per mode and records a
``SUBMISSION`` event exactly like the real ``ModeRuntime`` does, so the orchestrator sees the same
blackboard it would in production.
"""

from __future__ import annotations

import inspect
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from devpilot.config import Settings
from devpilot.core import models as m
from devpilot.core.events import EventType
from devpilot.core.ports import ModeInvocation, ToolContext
from devpilot.orchestrator.orchestrator import Orchestrator
from devpilot.state.blackboard import EventSourcedBlackboard
from devpilot.state.event_store import JsonlEventStore

MID = "M-test"

Script = BaseModel | Exception | Callable[[ModeInvocation], BaseModel | Awaitable[BaseModel]]


# ---------------------------------------------------------------------------------------------
# builders for model objects
# ---------------------------------------------------------------------------------------------


def make_spec(ambiguity: m.Ambiguity | None = None) -> m.MissionSpec:
    def ac(i: int, preserve: bool) -> m.AcceptanceCriterion:
        return m.AcceptanceCriterion(
            id=f"AC-{i}",
            given="10 items",
            when="page size 3",
            then=f"criterion {i} holds",
            verification_methods=[m.VerificationMethod.ACCEPTANCE_TEST],
            preserves_existing_behaviour=preserve,
        )

    return m.MissionSpec(
        restated_request="Fix the pager",
        objectives=["last page is shown"],
        acceptance_criteria=[ac(1, True), ac(2, False)],
        ambiguity=ambiguity or m.Ambiguity(level=m.Level.LOW),
        mission_kind="bugfix",
    )


def make_brief() -> m.RepoBrief:
    return m.RepoBrief(
        summary="pager lib", relevant_files=[], conventions_confirmed=[], risks=[], baseline_summary="ok"
    )


def make_plan(*tasks: tuple[str, list[str], list[str]]) -> m.Plan:
    """tasks: (key, files_to_touch, depends_on)."""
    spec = tasks or (("T1", ["src/pager.py"], []),)
    return m.Plan(
        rationale="fix it",
        tasks=[
            m.TaskDraft(
                key=k,
                title=f"Task {k}",
                description="d",
                acceptance_refs=["AC-1", "AC-2"],
                files_to_touch=files,
                depends_on=deps,
            )
            for k, files, deps in spec
        ],
    )


def make_suite() -> m.AcceptanceSuite:
    return m.AcceptanceSuite(
        tests=[
            m.AcceptanceTest(
                ac_id="AC-1", path="tests/test_acceptance.py", test_names=["test_ac1"], rationale="r"
            ),
            m.AcceptanceTest(
                ac_id="AC-2", path="tests/test_acceptance.py", test_names=["test_ac2"], rationale="r"
            ),
        ],
        expected_initial_state="mixed",
    )


def make_report(status: Literal["done", "blocked", "partial"] = "done", **kw: Any) -> m.ChangeReport:
    base: dict[str, Any] = {
        "status": status,
        "hypothesis": "h",
        "approach": "a",
        "files_changed": ["src/pager.py"],
    }
    base.update(kw)
    return m.ChangeReport(**base)


def make_decision(action: m.Action, **kw: Any) -> m.Decision:
    base: dict[str, Any] = {
        "action": action,
        "justification": "because",
        "cited_evidence": ["E-0003"],
        "expected_outcome": "progress",
        "confidence": 0.8,
        "fallback_if_fails": m.Action.ASK_HUMAN,
    }
    base.update(kw)
    return m.Decision(**base)


def make_triage(
    fp: str = "a91f03", owner: str | None = "T1", nodeid: str = "tests/test_acceptance.py::test_ac2"
) -> m.TriageReport:
    return m.TriageReport(
        items=[
            m.TriageItem(
                nodeid=nodeid,
                fingerprint=fp,
                error_type="AssertionError",
                category="regression",
                hypotheses=[
                    m.Hypothesis(statement="integer division drops the last page", rank=1, experiment="probe")
                ],
                implicated_locations=["src/pager.py:L41"],
                fix_direction="use ceiling division",
                confidence=0.9,
                likely_owner_task=owner,
            )
        ],
        summary="last page missing",
    )


def pass_verdict(ac_ids: tuple[str, ...] = ("AC-1", "AC-2")) -> m.VerifierVerdict:
    return m.VerifierVerdict(
        per_ac=[
            m.ACVerdict(
                ac_id=a,
                verdict="PASS",
                reasoning="holds",
                checks=[
                    m.CheckResult(
                        method=m.VerificationMethod.PROBE, passed=True, evidence_ids=[], detail="probe"
                    )
                ],
            )
            for a in ac_ids
        ],
        test_integrity_ok=True,
        overall="ACCEPT",
    )


def reject_verdict(counterexample: str = "total=0 -> observed 0 pages, expected 1") -> m.VerifierVerdict:
    return m.VerifierVerdict(
        per_ac=[
            m.ACVerdict(
                ac_id="AC-1",
                verdict="PASS",
                reasoning="holds",
                checks=[
                    m.CheckResult(
                        method=m.VerificationMethod.PROBE, passed=True, evidence_ids=[], detail="probe"
                    )
                ],
            ),
            m.ACVerdict(
                ac_id="AC-2",
                verdict="FAIL",
                reasoning="property test failed",
                counterexample=counterexample,
                checks=[
                    m.CheckResult(
                        method=m.VerificationMethod.PROPERTY,
                        passed=False,
                        evidence_ids=[],
                        detail="hypothesis",
                    )
                ],
            ),
        ],
        test_integrity_ok=True,
        overall="REJECT",
    )


def approve_review(inv: ModeInvocation) -> m.ReviewReport:
    return m.ReviewReport(lens=m.ReviewLens(inv.extra_context["lens"]), findings=[], decision="approve")


def pass_security(_: ModeInvocation) -> m.SecurityReport:
    return m.SecurityReport(findings=[], scanners_run=["secrets"], scanners_unavailable=[], decision="pass")


# ---------------------------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------------------------


class ScriptedRuntime:
    """AgentRuntime fake: per-mode queues of outputs; records SUBMISSION events like ModeRuntime."""

    def __init__(self, bb: EventSourcedBlackboard) -> None:
        self.bb = bb
        self.queues: dict[str, list[Script]] = {}
        self.calls: list[ModeInvocation] = []
        self.inbox_at_call: list[tuple[ModeInvocation, list[m.AgentMessage]]] = []
        self._n = itertools.count(1)

    def script(self, mode_id: str, *items: Script) -> ScriptedRuntime:
        """Queue outputs; the last item repeats forever."""
        self.queues.setdefault(mode_id, []).extend(items)
        return self

    def modes(self) -> list[str]:
        return [c.mode_id for c in self.calls]

    async def invoke(self, inv: ModeInvocation) -> BaseModel:
        self.calls.append(inv)
        mission = self.bb.mission
        task = mission.tasks.get(inv.task_key or "")
        self.inbox_at_call.append((inv, [mission.messages[i] for i in (task.inbox if task else [])]))
        queue = self.queues.get(inv.mode_id)
        if not queue:
            raise AssertionError(f"no script for mode {inv.mode_id}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, BaseModel):
            out = item
        else:
            res = item(inv)
            out = await res if inspect.isawaitable(res) else res
        usage = m.LLMUsage(model="scripted", tokens_in=100, tokens_out=50, cost_usd=0.01, latency_ms=2000)
        await self.bb.emit(
            EventType.LLM_TURN,
            inv.agent_id,
            {"usage": usage},
            mode_id=inv.mode_id,
            task_key=inv.task_key,
            summary=f"{inv.mode_id} turn",
        )
        sub = m.Submission(
            id=f"S-{next(self._n):04d}",
            mode_id=inv.mode_id,
            agent_id=inv.agent_id,
            model="scripted",
            task_key=inv.task_key,
            attempt=inv.attempt,
            output_type=type(out).__name__,
            payload=out.model_dump(mode="json"),
            usage=[usage],
        )
        await self.bb.emit(
            EventType.SUBMISSION,
            inv.agent_id,
            {"submission": sub},
            mode_id=inv.mode_id,
            task_key=inv.task_key,
            summary=f"{inv.mode_id} submitted {sub.output_type}",
        )
        return out


class FakeWorkspaces:
    """Workspaces fake. ``edit()`` simulates a Samurai edit (the tree sha changes)."""

    def __init__(self) -> None:
        self.n = 0
        self.checkpoints = 0
        self.rollbacks: list[str] = []
        self.applied = 0
        self.apply_error: Exception | None = None
        self.diff_text = "diff --git a/src/pager.py b/src/pager.py\n--- a/src/pager.py\n+++ b/src/pager.py\n"

    def edit(self) -> None:
        self.n += 1

    async def create_main(self, repo: Path, mission_id: str) -> Path:
        return Path("/ws")

    async def create_baseline(self) -> Path:
        return Path("/baseline")

    async def fork(self, name: str, from_ref: str = "main") -> Path:
        return Path("/ws-" + name)

    async def path(self, ref: str) -> Path:
        return Path("/ws")

    async def tree_sha(self, ref: str = "main") -> str:
        return f"tree{self.n}"

    async def diff(self, ref: str = "main", against: str = "baseline") -> str:
        return self.diff_text

    async def hunks(self, ref: str = "main") -> list[dict[str, Any]]:
        return []

    async def checkpoint(self, label: str, ref: str = "main") -> str:
        self.checkpoints += 1
        return f"cp{self.checkpoints}"

    async def rollback(self, sha: str, ref: str = "main") -> None:
        self.rollbacks.append(sha)

    async def adopt(self, candidate: str) -> None:
        self.n += 1

    async def apply_to_target(self) -> str:
        if self.apply_error:
            raise self.apply_error
        self.applied += 1
        return "merge-sha"


def make_run(
    scope: Literal["targeted", "full", "acceptance", "probe", "baseline"],
    *,
    n: int,
    red: bool = False,
    fp: str = "a91f03",
    regression: bool = False,
    failing: tuple[str, ...] = ("test_ac2",),
) -> m.TestRun:
    names = ["test_ac1", "test_ac2"]
    cases: list[m.TestCaseResult] = []
    for name in names:
        bad = red and name in failing
        cases.append(
            m.TestCaseResult(
                nodeid=f"tests/test_acceptance.py::{name}",
                outcome=m.TestOutcome.FAILED if bad else m.TestOutcome.PASSED,
                baseline_outcome=m.TestOutcome.PASSED,
                classification=(m.TestClass.REGRESSION if regression else m.TestClass.EXPECTED_RED)
                if bad
                else m.TestClass.STILL_PASSING,
                fingerprint=fp if bad else None,
                is_acceptance=True,
            )
        )
    nbad = sum(1 for c in cases if c.outcome == m.TestOutcome.FAILED)
    return m.TestRun(
        id=f"TR-{n}",
        evidence_id=f"E-{n:04d}",
        scope=scope,
        workspace_ref="main",
        totals={"passed": len(cases) - nbad, "failed": nbad},
        cases=cases,
        regressions=[c.nodeid for c in cases if c.outcome == m.TestOutcome.FAILED] if regression else [],
        verdict="red" if red else "green",
    )


Spec = Callable[[int], m.TestRun]


class FakeTestRunner:
    """Scripted TestRunner: ``plan`` entries are consumed in call order; the last one repeats."""

    def __init__(self, plan: list[Spec]) -> None:
        self.plan = plan
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def run(
        self, scope: Any, workspace_ref: str = "main", selectors: Any = (), ctx: ToolContext | None = None
    ) -> m.TestRun:
        n = len(self.calls) + 1
        self.calls.append((scope, tuple(selectors)))
        build = self.plan[min(n, len(self.plan)) - 1]
        run = build(n)
        return run.model_copy(update={"scope": scope})

    async def rerun_isolated(self, nodeid: str, times: int = 2, workspace_ref: str = "main") -> list[bool]:
        return [True] * times


def green(n: int) -> m.TestRun:
    return make_run("full", n=n)


def red(fp: str = "a91f03", **kw: Any) -> Spec:
    return lambda n: make_run("full", n=n, red=True, fp=fp, **kw)


class FakeHuman:
    """HumanChannel fake: ``handler(prompt) -> (choice, free_text)``."""

    def __init__(self, handler: Callable[[m.HumanPrompt], tuple[str | None, str | None]]) -> None:
        self.handler = handler
        self.prompts: list[m.HumanPrompt] = []

    async def ask(self, prompt: m.HumanPrompt) -> m.HumanDecision:
        self.prompts.append(prompt)
        choice, text = self.handler(prompt)
        return m.HumanDecision(
            id=f"HD-{len(self.prompts)}", prompt_id=prompt.id, choice=choice, free_text=text
        )


def approve_all(prompt: m.HumanPrompt) -> tuple[str | None, str | None]:
    return {"apply": "approve", "plan": "approve"}.get(prompt.gate, "accept_partial"), None


# ---------------------------------------------------------------------------------------------
# world
# ---------------------------------------------------------------------------------------------


@dataclass
class World:
    store: JsonlEventStore
    bb: EventSourcedBlackboard
    rt: ScriptedRuntime
    ws: FakeWorkspaces
    tests: FakeTestRunner
    human: FakeHuman
    orch: Orchestrator
    reports: list[m.Mission] = field(default_factory=list)


async def make_world(
    tmp_path: Path,
    *,
    plan: list[Spec],
    human: Callable[[m.HumanPrompt], tuple[str | None, str | None]] = approve_all,
    limits: m.Budgets | None = None,
    settings: Settings | None = None,
    tournament: Callable[..., Awaitable[str]] | None = None,
    base_scripts: bool = True,
    spec: m.MissionSpec | None = None,
    **orch_kw: Any,
) -> World:
    store = JsonlEventStore(tmp_path / "runs")
    mission = m.Mission(
        id=MID,
        request="Last page of results is missing items",
        repo_path="/repo",
        workspace_path="/ws",
        budget=m.BudgetState(limits=limits or m.Budgets()),
    )
    bb = await EventSourcedBlackboard.create(store, mission)
    rt = ScriptedRuntime(bb)
    ws = FakeWorkspaces()
    tests = FakeTestRunner(plan)
    fh = FakeHuman(human)
    reports: list[m.Mission] = []

    async def writer(mi: m.Mission) -> None:
        reports.append(mi.model_copy(deep=True))

    kw: dict[str, Any] = {"report_writer": writer}
    kw.update(orch_kw)
    orch = Orchestrator(bb, rt, ws, tests, fh, settings or Settings(), tournament=tournament, **kw)
    if base_scripts:
        rt.script("scout.recon", make_brief())
        rt.script("shogun.analyze", spec or make_spec())
        rt.script("shogun.plan", make_plan())
        rt.script("shogun.premortem", m.PreMortem(risks=[]))
        rt.script("sentinel.author_acceptance", make_suite())
        rt.script("shogun.reflect", m.Reflection(what_worked=[], what_failed=[], lessons=[]))
        rt.script("reviewer.review", approve_review)
        rt.script("security.inspect", pass_security)
    w = World(store, bb, rt, ws, tests, fh, orch, reports)
    return w


def samurai(
    ws: FakeWorkspaces, report: m.ChangeReport | None = None
) -> Callable[[ModeInvocation], m.ChangeReport]:
    """A Samurai script step that edits the workspace (tree sha changes) and reports done."""

    def step(_: ModeInvocation) -> m.ChangeReport:
        ws.edit()
        return report or make_report()

    return step


async def events_of(w: World) -> list[Any]:
    return await w.store.read(MID)


def kinds(events: list[Any]) -> list[str]:
    return [e.type.value for e in events]


async def assert_replay_matches(w: World) -> None:
    """Event-sourcing integrity: loading from disk reproduces the live mission exactly."""
    loaded = await EventSourcedBlackboard.load(w.store, MID)
    assert loaded.mission.model_dump(mode="json") == w.bb.mission.model_dump(mode="json")
