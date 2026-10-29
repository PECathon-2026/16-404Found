"""Shared builders and fakes for the engine tests (imported as ``engine_helpers``)."""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from devpilot.config import Settings
from devpilot.core import models as m
from devpilot.core.events import Event
from devpilot.core.ports import LLMRequest, LLMResponse, ToolContext, ToolResult, ToolSchema
from devpilot.engine.context import ContextServices
from devpilot.engine.runtime import ModeRuntime
from devpilot.llm.fake import ScriptedLLM
from devpilot.state.blackboard import EventSourcedBlackboard
from devpilot.state.event_store import JsonlEventStore

SECRET_HYPOTHESIS = "ZEBRA-HYPOTHESIS: off-by-one in the pager floor division"
MID = "M-1"


def make_ac(ac_id: str, *, preserve: bool = False, priority: str = "must") -> m.AcceptanceCriterion:
    return m.AcceptanceCriterion(
        id=ac_id,
        given="a list of 10 items",
        when="page size is 3",
        then="there are 4 pages",
        verification_methods=[m.VerificationMethod.ACCEPTANCE_TEST],
        preserves_existing_behaviour=preserve,
        priority=priority,  # type: ignore[arg-type]
    )


def make_spec(*ids: str) -> m.MissionSpec:
    ids = ids or ("AC-1", "AC-2")
    return m.MissionSpec(
        restated_request="Fix the pager",
        objectives=["pages are counted correctly"],
        acceptance_criteria=[make_ac(i, preserve=(n == 0)) for n, i in enumerate(ids)],
        ambiguity=m.Ambiguity(level=m.Level.LOW),
        mission_kind="bugfix",
    )


def make_intel() -> m.RepoIntel:
    return m.RepoIntel(
        languages={"python": 12},
        file_count=30,
        test_framework="pytest",
        test_command=["pytest", "-q"],
        repo_map=[
            m.Symbol(
                name="paginate",
                qualname="pager.paginate",
                kind="function",
                path="src/pager.py",
                line_start=10,
                line_end=30,
                signature="(items, size)",
                rank=0.9,
            ),
        ],
        conventions=[m.ConventionStat(aspect="typing", observation="fully typed", confidence=0.9)],
        risks=[m.FileRisk(path="src/pager.py", churn=5, complexity=3.0, coverage=0.5, risk_score=0.7)],
    )


def make_brief() -> m.RepoBrief:
    return m.RepoBrief(
        summary="A small pager library.",
        relevant_files=[m.RelevantFile(path="src/pager.py", reason="has paginate")],
        conventions_confirmed=[],
        risks=["no tests for rounding"],
        baseline_summary="3 passed, 1 failed",
    )


def make_task(key: str = "T1", **kw: Any) -> m.Task:
    base: dict[str, Any] = {
        "id": f"task-{key}",
        "key": key,
        "title": "Fix paginate",
        "description": "Use ceiling division",
        "acceptance_refs": ["AC-1", "AC-2"],
        "files_to_touch": ["src/pager.py"],
        "depends_on": [],
        "may_edit_tests": False,
        "risk": m.Level.MEDIUM,
        "plan_version": 1,
        "status": m.TaskStatus.IN_PROGRESS,
        "attempts": [
            m.Attempt(
                n=1,
                mode_id="samurai.implement",
                agent_id="samurai#1",
                model="m",
                fingerprints=["fp-aaaa"],
                hypothesis=SECRET_HYPOTHESIS,
                outcome="red",
            ),
        ],
        "inbox": ["MSG-1"],
    }
    base.update(kw)
    return m.Task(**base)


def make_change_report_payload(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "done",
        "hypothesis": SECRET_HYPOTHESIS,
        "approach": "ceil division",
        "files_changed": ["src/pager.py"],
    }
    base.update(kw)
    return base


def make_test_run() -> m.TestRun:
    def case(node: str, out: m.TestOutcome, cls: m.TestClass, fp: str | None = None) -> m.TestCaseResult:
        return m.TestCaseResult(
            nodeid=node,
            outcome=out,
            baseline_outcome=m.TestOutcome.PASSED,
            classification=cls,
            fingerprint=fp,
            message="boom" if fp else None,
        )

    return m.TestRun(
        id="TR-1",
        evidence_id="E-0002",
        scope="full",
        workspace_ref="main",
        totals={"passed": 1, "failed": 1},
        cases=[
            case("tests/test_a.py::test_ok", m.TestOutcome.PASSED, m.TestClass.STILL_PASSING),
            case("tests/test_a.py::test_bad", m.TestOutcome.FAILED, m.TestClass.REGRESSION, "fp-aaaa"),
        ],
        regressions=["tests/test_a.py::test_bad"],
        verdict="red",
    )


def make_evidence(eid: str, kind: m.EvidenceKind = m.EvidenceKind.TEST_RUN) -> m.Evidence:
    return m.Evidence(
        id=eid,
        kind=kind,
        tool="test.run",
        agent_id="a",
        workspace_ref="main",
        workspace_sha="x",
        summary="s",
        log_path="l",
        sha256="0" * 64,
    )


def make_mission(**kw: Any) -> m.Mission:
    """A realistic mid-flight mission: intel, brief, spec, plan, task with history, a ChangeReport."""
    spec = make_spec()
    plan = m.Plan(
        rationale="one task",
        tasks=[
            m.TaskDraft(
                key="T1",
                title="Fix paginate",
                description="d",
                acceptance_refs=["AC-1", "AC-2"],
                files_to_touch=["src/pager.py"],
            )
        ],
    )
    sub = m.Submission(
        id="S-cr1",
        mode_id="samurai.implement",
        agent_id="samurai#1",
        model="m",
        task_key="T1",
        attempt=1,
        output_type="ChangeReport",
        payload=make_change_report_payload(),
    )
    msg = m.AgentMessage(
        id="MSG-1",
        sender="sentinel#1",
        to="task:T1",
        type=m.MessageType.FINDING,
        subject="pager fails",
        body="test_bad regressed",
        evidence_ids=["E-0002"],
    )
    base: dict[str, Any] = {
        "id": MID,
        "request": "Fix the pager so 10 items / size 3 gives 4 pages",
        "repo_path": "/repo",
        "workspace_path": "/ws",
        "intel": make_intel(),
        "brief": make_brief(),
        "spec": spec,
        "acs": [m.ACState(ac=a) for a in spec.acceptance_criteria],
        "plans": [m.PlanRecord(id="plan-1", version=1, plan=plan)],
        "tasks": {"T1": make_task()},
        "submissions": {sub.id: sub},
        "messages": {msg.id: msg},
        "test_runs": [make_test_run()],
        "evidence": {"E-0001": make_evidence("E-0001"), "E-0002": make_evidence("E-0002")},
    }
    base.update(kw)
    return m.Mission(**base)


class FakeWorkspaces:
    """Minimal ``Workspaces`` double: a fixed diff, hunks and a real directory for ``path``."""

    def __init__(self, root: Path, diff: str = "", hunks: list[dict[str, Any]] | None = None) -> None:
        self.root, self._diff, self._hunks = root, diff, hunks or []

    async def diff(self, ref: str = "main", against: str = "baseline") -> str:
        return self._diff

    async def hunks(self, ref: str = "main") -> list[dict[str, Any]]:
        return self._hunks

    async def path(self, ref: str) -> Path:
        return self.root


class FakeGateway:
    """Records calls (with timings) and returns canned results; ``delays`` makes concurrency observable."""

    def __init__(
        self, results: dict[str, ToolResult] | None = None, delays: dict[str, float] | None = None
    ) -> None:
        self.results = results or {}
        self.delays = delays or {}
        self.calls: list[tuple[str, dict[str, Any], ToolContext]] = []
        self.starts: dict[str, float] = {}
        self.ends: dict[str, float] = {}
        self.order: list[str] = []

    def schemas(self, tool_names: Sequence[str]) -> list[ToolSchema]:
        return [
            ToolSchema(n.replace(".", "_"), f"tool {n}", {"type": "object", "properties": {}})
            for n in tool_names
        ]

    async def execute(self, ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
        key = str(args.get("tag", name))
        self.calls.append((name, args, ctx))
        self.order.append(f"start:{key}")
        self.starts[key] = time.monotonic()
        await asyncio.sleep(self.delays.get(key, 0))
        self.ends[key] = time.monotonic()
        self.order.append(f"end:{key}")
        return self.results.get(name) or ToolResult(ok=True, tool=name, output=f"out of {key}")


class RecordingLLM(ScriptedLLM):
    """ScriptedLLM that also keeps deep copies of every request's messages (to prove append-only)."""

    def __init__(self, responses: list[LLMResponse], model: str | None = None) -> None:
        super().__init__(responses)  # type: ignore[arg-type]
        self.snapshots: list[list[dict[str, Any]]] = []
        self._model = model

    def resolve(self, tier: m.ModelTier) -> str:
        return self._model or super().resolve(tier)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.snapshots.append(copy.deepcopy(req.messages))
        return await super().complete(req)


def cache_markers(req: LLMRequest) -> int:
    n = sum(1 for t in req.tools if t.cache) + sum(1 for s in req.system if s.cache)
    for msg in req.messages:
        content = msg["content"]
        if isinstance(content, list):
            n += sum(1 for b in content if isinstance(b, dict) and "cache_control" in b)
    return n


class Rig:
    """Everything a runtime test needs."""

    def __init__(
        self,
        rt: ModeRuntime,
        bb: EventSourcedBlackboard,
        llm: RecordingLLM,
        gw: FakeGateway,
        store: JsonlEventStore,
    ) -> None:
        self.rt, self.bb, self.llm, self.gw, self.store = rt, bb, llm, gw, store

    async def events(self) -> list[Event]:
        return await self.store.read(MID)

    async def types(self) -> list[str]:
        return [e.type.value for e in await self.events()]


async def make_rig(
    tmp_path: Path,
    responses: list[LLMResponse],
    *,
    gateway: FakeGateway | None = None,
    services: ContextServices | None = None,
    mission: m.Mission | None = None,
    model: str | None = None,
    debug: bool = True,
    **rt_kw: Any,
) -> Rig:
    store = JsonlEventStore(tmp_path / "runs")
    bb = await EventSourcedBlackboard.create(store, mission or make_mission())
    llm = RecordingLLM(responses, model)
    gw = gateway or FakeGateway()
    rt = ModeRuntime(
        bb,
        llm,
        gw,
        services or ContextServices(),
        Settings(),
        prompt_source=lambda mode_id: f"PROMPT for {mode_id}",
        constitution=lambda: "CONSTITUTION",
        debug=debug,
        **rt_kw,
    )
    return Rig(rt, bb, llm, gw, store)
