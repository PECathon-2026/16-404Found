"""Composition root: assemble the real components into one runnable mission (the only place that
imports concrete classes across subsystems).

Components owned by packets that may not have landed yet (tool registry G04, test runner G05, repo
intel G06, delta debugger) are *discovered*: ``build_stack`` try-imports them and carries on without
them. ``missing_components`` reports what is absent, and ``devpilot run`` refuses to start without a
test runner unless told otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from devpilot.config import Settings
from devpilot.core.events import Event
from devpilot.core.models import BudgetState, Evidence, Mission
from devpilot.core.ports import (
    AgentRuntime,
    Blackboard,
    DeltaDebugger,
    EvidenceLedger,
    Executor,
    HumanChannel,
    LLMPort,
    RepoIntelService,
    TestRunner,
    Workspaces,
)
from devpilot.engine.context import ContextServices
from devpilot.engine.runtime import ModeRuntime
from devpilot.human import AnswersFileHumanChannel, ConsoleHumanChannel
from devpilot.llm import AnthropicLLM, CassetteLLM
from devpilot.orchestrator.orchestrator import Orchestrator
from devpilot.state.blackboard import EventSourcedBlackboard
from devpilot.state.event_store import JsonlEventStore
from devpilot.tools.executor_local import LocalExecutor
from devpilot.tools.gateway import DefaultToolGateway
from devpilot.tools.ledger import FileEvidenceLedger
from devpilot.workspace.git_worktrees import GitWorkspaces

log = logging.getLogger(__name__)

CassetteMode = Literal["record", "replay", "passthrough"]

# --------------------------------------------------------------------------------------
# discovery of components owned by other packets
# --------------------------------------------------------------------------------------

#: component -> (packet, candidate modules, class-name hint, methods the class must have)
COMPONENTS: dict[str, tuple[str, tuple[str, ...], str, tuple[str, ...]]] = {
    "test runner": ("WP-G05", ("devpilot.testing.runner",), "runner", ("run", "rerun_isolated")),
    "repo intel": (
        "WP-G06",
        ("devpilot.intel.service", "devpilot.intel", "devpilot.repo_intel"),
        "intel",
        ("build", "rerank", "callers_of", "tests_covering"),
    ),
    "delta debugger": (
        "WP-C06",
        ("devpilot.testing.ddmin", "devpilot.triage.ddmin", "devpilot.triage"),
        "debug",
        ("isolate",),
    ),
}
TOOL_REGISTRY_MODULE = "devpilot.tools.registry"
TOOL_REGISTRY_PACKET = "WP-G04"


class WiringError(RuntimeError):
    """The stack cannot be assembled (bad arguments, missing credentials, ...)."""


class ComponentUnavailableError(RuntimeError):
    """Raised by placeholder components standing in for a packet that has not landed."""


def _try_import(name: str) -> Any | None:
    """Import ``name``; ``None`` when it (or a parent package) does not exist. Other errors are logged."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name and (name == exc.name or name.startswith(exc.name + ".")):
            return None
        log.warning("importing %s failed: %s", name, exc)
    except Exception as exc:
        log.warning("importing %s failed: %s", name, exc)
    return None


def _find_class(modules: tuple[str, ...], methods: tuple[str, ...], hint: str) -> type | None:
    """First class defined in the first importable module that has all of ``methods``."""
    for name in modules:
        mod = _try_import(name)
        if mod is None:
            continue
        found = [
            c
            for c in vars(mod).values()
            if inspect.isclass(c)
            and c.__module__ == mod.__name__
            and not inspect.isabstract(c)
            and all(callable(getattr(c, mth, None)) for mth in methods)
        ]
        found.sort(key=lambda c: (hint not in c.__name__.lower(), c.__name__))
        if found:
            return found[0]
    return None


def _construct(cls: type, available: dict[str, Any]) -> Any | None:
    """Instantiate ``cls`` passing the services whose names match its parameters.

    Parameters we cannot satisfy and that have no default make construction fail (``None``)."""
    try:
        params = inspect.signature(cls).parameters.values()
    except (TypeError, ValueError):
        return None
    kwargs: dict[str, Any] = {}
    for p in params:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.name in available:
            kwargs[p.name] = available[p.name]
        elif p.default is p.empty:
            log.warning("cannot construct %s: unknown required parameter %r", cls.__name__, p.name)
            return None
    try:
        return cls(**kwargs)
    except Exception as exc:
        log.warning("constructing %s failed: %s", cls.__name__, exc)
        return None


def probe_components() -> dict[str, bool]:
    """Which discoverable components are importable (no side effects); keys are display names."""
    out = {"tool registry": _try_import(TOOL_REGISTRY_MODULE) is not None}
    for name, (_, modules, hint, methods) in COMPONENTS.items():
        out[name] = _find_class(modules, methods, hint) is not None
    return out


def packet_of(component: str) -> str:
    return TOOL_REGISTRY_PACKET if component == "tool registry" else COMPONENTS[component][0]


# --------------------------------------------------------------------------------------
# event bridge: sync gateway callback -> ordered, async blackboard.emit
# --------------------------------------------------------------------------------------


class EventBridge:
    """Carries the gateway's synchronous ``event_callback`` events onto the blackboard in order."""

    def __init__(self, blackboard: EventSourcedBlackboard | Any) -> None:
        self._bb = blackboard
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.delivered = 0
        self.failed = 0

    def start(self) -> None:
        if self._task is None:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(self._consume(), name="event-bridge")

    def __call__(self, event: Event) -> None:
        """The gateway's callback. Safe from the loop thread or any other thread."""
        loop = self._loop
        if loop is None:
            self._queue.put_nowait(event)  # not started yet: delivered once start() runs
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._queue.put_nowait(event)
        else:
            loop.call_soon_threadsafe(self._queue.put_nowait, event)

    async def _consume(self) -> None:
        while True:
            ev = await self._queue.get()
            try:
                await self._bb.emit(
                    ev.type,
                    ev.actor,
                    ev.payload,
                    mode_id=ev.mode_id,
                    task_key=ev.task_key,
                    summary=ev.summary,
                )
                self.delivered += 1
            except Exception:
                self.failed += 1
                log.exception("event bridge could not emit %s", ev.type)
            finally:
                self._queue.task_done()

    async def drain(self) -> None:
        """Wait until everything enqueued so far has been emitted."""
        if self._task is not None and not self._task.done():
            await self._queue.join()

    async def close(self) -> None:
        await self.drain()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


# --------------------------------------------------------------------------------------
# placeholders and adapters
# --------------------------------------------------------------------------------------


class UnavailableTestRunner:
    """Stands in until WP-G05 lands; every call fails loudly so the mission ends FAILED, not green."""

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        raise ComponentUnavailableError("test runner is not available (WP-G05)")

    async def rerun_isolated(self, *args: Any, **kwargs: Any) -> list[bool]:
        raise ComponentUnavailableError("test runner is not available (WP-G05)")


class MissionEvidenceLedger:
    """One evidence-id sequence per mission over :class:`FileEvidenceLedger`.

    The file ledger numbers (and keys) evidence by ``workspace_ref``, so ``main`` and ``baseline``
    would both mint ``E-0001``. Here every record is filed under the mission, giving
    ``runs/<id>/evidence/E-NNNN.log`` with mission-wide unique ids; ``Evidence.workspace_ref`` keeps
    its real value.
    """

    def __init__(self, runs_dir: Path, mission_id: str) -> None:
        self._mission_id = mission_id
        self._inner = FileEvidenceLedger(runs_dir)
        self._records: dict[str, Evidence] = {}

    async def record(self, ev: Evidence, raw_output: str) -> Evidence:
        stored = await self._inner.record(
            ev.model_copy(update={"workspace_ref": self._mission_id}), raw_output
        )
        final = stored.model_copy(update={"workspace_ref": ev.workspace_ref})
        self._records[final.id] = final
        return final

    def get(self, evidence_id: str) -> Evidence:
        try:
            return self._records[evidence_id]
        except KeyError:
            raise KeyError(f"Evidence record {evidence_id!r} not found in ledger") from None

    def exists(self, evidence_id: str) -> bool:
        return evidence_id in self._records


@dataclass(slots=True)
class ToolRegistryContext:
    """What ``devpilot.tools.registry.register_all(gateway, ctx)`` receives."""

    mission_id: str
    settings: Settings
    workspaces: Workspaces
    executor: Executor
    ledger: EvidenceLedger
    runs_dir: Path
    repo_intel: RepoIntelService | None = None
    test_runner: TestRunner | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------------------
# the stack
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class MissionStack:
    settings: Settings
    mission_id: str
    runs_dir: Path
    repo: Path
    store: JsonlEventStore
    blackboard: EventSourcedBlackboard
    workspaces: Workspaces
    ledger: EvidenceLedger
    executor: Executor
    gateway: DefaultToolGateway
    bridge: EventBridge
    llm: LLMPort
    services: ContextServices
    runtime: AgentRuntime
    human: HumanChannel
    tests: TestRunner
    orchestrator: Orchestrator
    repo_intel: RepoIntelService | None = None
    ddmin: DeltaDebugger | None = None
    tools_registered: bool = False
    tests_available: bool = False
    cassette_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    async def shutdown(self) -> None:
        """Drain the event bridge, then release worktree registrations (when supported)."""
        await self.bridge.close()
        cleanup = getattr(self.workspaces, "cleanup", None)  # GitWorkspaces.cleanup: G03 review R4
        if cleanup is not None:
            try:
                res = cleanup()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                log.exception("workspace cleanup failed")


def missing_components(stack: MissionStack) -> list[str]:
    """Human-readable list of unavailable components, each naming the packet that provides it."""
    out: list[str] = []
    if not stack.tools_registered:
        out.append(f"tool registry ({TOOL_REGISTRY_PACKET})")
    if not stack.tests_available:
        out.append(f"test runner ({COMPONENTS['test runner'][0]})")
    if stack.repo_intel is None:
        out.append(f"repo intel ({COMPONENTS['repo intel'][0]})")
    if stack.ddmin is None:
        out.append(f"delta debugger ({COMPONENTS['delta debugger'][0]})")
    return out


def new_mission_id(now: datetime | None = None) -> str:
    return f"M-{(now or datetime.now(UTC)).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


async def _register_tools(gateway: DefaultToolGateway, ctx: ToolRegistryContext, notes: list[str]) -> bool:
    mod = _try_import(TOOL_REGISTRY_MODULE)
    register = getattr(mod, "register_all", None) if mod is not None else None
    if register is None:
        notes.append(
            f"tools unavailable: {TOOL_REGISTRY_MODULE} not found ({TOOL_REGISTRY_PACKET}); "
            "tool calls will return TOOL_UNAVAILABLE"
        )
        log.warning(notes[-1])
        return False
    try:
        res = register(gateway, ctx)
        if inspect.isawaitable(res):
            await res
    except Exception as exc:
        notes.append(f"tool registration failed: {type(exc).__name__}: {exc}")
        log.exception("tool registration failed")
        return False
    return True


def _make_llm(
    settings: Settings, mission_id: str, runs_dir: Path, cassette: Path | None, mode: CassetteMode
) -> tuple[LLMPort, Path]:
    path = cassette or runs_dir / mission_id / "cassette.jsonl"
    if mode == "replay":
        return CassetteLLM(None, path, "replay"), path
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise WiringError("ANTHROPIC_API_KEY is not set (use --replay FILE to run offline from a cassette)")
    path.parent.mkdir(parents=True, exist_ok=True)
    return CassetteLLM(AnthropicLLM(settings), path, mode), path


async def build_stack(
    settings: Settings,
    *,
    repo: Path,
    request: str,
    mode: Literal["multi", "single"] = "multi",
    runs_dir: Path,
    cassette: Path | None = None,
    cassette_mode: CassetteMode = "record",
    answers: Path | None = None,
    human: HumanChannel | None = None,
    llm: LLMPort | None = None,
    overrides: dict[str, Any] | None = None,
) -> MissionStack:
    """Assemble every component for one mission.

    ``llm`` and ``overrides`` inject fakes. Recognised override keys: ``runtime`` (an AgentRuntime or a
    ``callable(blackboard) -> AgentRuntime``), ``tests``, ``repo_intel``, ``ddmin``, ``workspaces``,
    ``tool_registry`` (a ``register_all``-style callable replacing discovery).
    """
    ov = dict(overrides or {})
    runs_dir = Path(runs_dir)
    repo = Path(repo)
    mission_id = new_mission_id()
    notes: list[str] = []

    store = JsonlEventStore(runs_dir)
    workspaces: Workspaces = ov.get("workspaces") or GitWorkspaces(runs_dir)
    main_path = await workspaces.create_main(repo, mission_id)
    await workspaces.create_baseline()

    mission = Mission(
        id=mission_id,
        request=request,
        repo_path=str(repo.resolve()),
        workspace_path=str(main_path),
        mode=mode,
        budget=BudgetState(limits=settings.budgets.model_copy()),
    )
    bb = await EventSourcedBlackboard.create(store, mission)

    ledger = MissionEvidenceLedger(runs_dir, mission_id)
    bridge = EventBridge(bb)
    gateway = DefaultToolGateway(
        ledger, event_callback=bridge, disabled_tools=tuple(settings.chaos.disable_tools)
    )
    bridge.start()
    executor = LocalExecutor()

    # --- discovered components (other packets) ---------------------------------------------
    available: dict[str, Any] = {
        "workspaces": workspaces,
        "executor": executor,
        "ledger": ledger,
        "settings": settings,
        "runs_dir": runs_dir,
        "mission_id": mission_id,
        "gateway": gateway,
    }

    def discover(key: str, override: str) -> Any | None:
        if override in ov:
            return ov[override]
        _, modules, hint, methods = COMPONENTS[key]
        cls = _find_class(modules, methods, hint)
        return _construct(cls, available) if cls is not None else None

    tests = discover("test runner", "tests")
    repo_intel: RepoIntelService | None = discover("repo intel", "repo_intel")
    ddmin: DeltaDebugger | None = discover("delta debugger", "ddmin")
    if repo_intel is not None:
        available["repo_intel"] = repo_intel
    if tests is not None:
        available["test_runner"] = tests

    tool_ctx = ToolRegistryContext(
        mission_id=mission_id,
        settings=settings,
        workspaces=workspaces,
        executor=executor,
        ledger=ledger,
        runs_dir=runs_dir,
        repo_intel=repo_intel,
        test_runner=tests,
    )
    if "tool_registry" in ov:
        res = ov["tool_registry"](gateway, tool_ctx)
        if inspect.isawaitable(res):
            await res
        tools_registered = True
    else:
        tools_registered = await _register_tools(gateway, tool_ctx, notes)

    # --- LLM, runtime, orchestrator ---------------------------------------------------------
    cassette_path: Path | None = None
    if llm is None:
        llm, cassette_path = _make_llm(settings, mission_id, runs_dir, cassette, cassette_mode)

    # EventSourcedBlackboard.emit has keyword-only extras where the port says **kw: a typing-only mismatch.
    port_bb = cast(Blackboard, bb)
    services = ContextServices(workspaces=workspaces, repo_intel=repo_intel)
    runtime_ov = ov.get("runtime")
    runtime: AgentRuntime
    if runtime_ov is None:
        runtime = ModeRuntime(
            port_bb, llm, gateway, services, settings, validation_hooks={"evidence_exists": ledger.exists}
        )
    elif callable(runtime_ov) and not hasattr(runtime_ov, "invoke"):
        runtime = runtime_ov(bb)
    else:
        runtime = runtime_ov

    if human is None:
        human = AnswersFileHumanChannel(answers) if answers is not None else ConsoleHumanChannel()
    attach: Callable[[Workspaces, Any], None] | None = getattr(human, "attach", None)
    if attach is not None:
        attach(workspaces, bb)

    tests_available = tests is not None
    runner: TestRunner = tests if tests is not None else UnavailableTestRunner()
    orchestrator = Orchestrator(
        port_bb, runtime, workspaces, runner, human, settings, repo_intel=repo_intel, ddmin=ddmin
    )
    for n in notes:
        log.info(n)
    return MissionStack(
        settings=settings,
        mission_id=mission_id,
        runs_dir=runs_dir,
        repo=repo,
        store=store,
        blackboard=bb,
        workspaces=workspaces,
        ledger=ledger,
        executor=executor,
        gateway=gateway,
        bridge=bridge,
        llm=llm,
        services=services,
        runtime=runtime,
        human=human,
        tests=runner,
        orchestrator=orchestrator,
        repo_intel=repo_intel,
        ddmin=ddmin,
        tools_registered=tools_registered,
        tests_available=tests_available,
        cassette_path=cassette_path,
        notes=notes,
    )


__all__ = [
    "COMPONENTS",
    "ComponentUnavailableError",
    "EventBridge",
    "MissionEvidenceLedger",
    "MissionStack",
    "ToolRegistryContext",
    "UnavailableTestRunner",
    "WiringError",
    "build_stack",
    "missing_components",
    "new_mission_id",
    "probe_components",
]
