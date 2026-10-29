"""Ports: the interfaces each subsystem implements. The orchestrator depends only on these,
which lets Gemini/humans build adapters in parallel and lets tests use fakes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from devpilot.core.events import Event, EventType
from devpilot.core.models import (
    Evidence,
    EvidenceKind,
    HumanDecision,
    HumanPrompt,
    LLMUsage,
    MemoryItem,
    Mission,
    ModelTier,
    RepoIntel,
    TestRun,
)

# --------------------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class ToolSchema:
    name: str  # API-safe name, e.g. "fs_edit"
    description: str
    input_schema: dict[str, Any]
    cache: bool = False  # place a prompt-cache breakpoint after the tool list


@dataclass(slots=True)
class PromptBlock:
    text: str
    cache: bool = False  # cache breakpoint after this block


@dataclass(slots=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    text: str
    thinking_summary: str | None
    tool_uses: list[ToolUse]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]
    usage: LLMUsage
    raw_assistant_content: list[dict[str, Any]]  # to append verbatim to the conversation


@dataclass(slots=True)
class LLMRequest:
    tier: ModelTier
    system: list[PromptBlock]
    messages: list[dict[str, Any]]
    tools: list[ToolSchema]
    tool_choice: dict[str, Any] | None = None  # e.g. {"type": "tool", "name": "submit_plan"}
    thinking_budget: int | None = None
    max_output_tokens: int = 8000
    model_override: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)  # mission/mode/agent ids for tracing


class LLMPort(Protocol):
    async def complete(self, req: LLMRequest) -> LLMResponse: ...

    def stream(self, req: LLMRequest) -> AsyncIterator[str | LLMResponse]:
        """Yields text deltas, then a final LLMResponse."""
        ...

    def resolve(self, tier: ModelTier) -> str: ...


# --------------------------------------------------------------------------------------
# Events & state
# --------------------------------------------------------------------------------------


class EventStore(Protocol):
    async def append(self, event: Event) -> Event:
        """Assigns seq, persists (unless ephemeral), fans out to subscribers. Returns stored event."""
        ...

    def subscribe(self, mission_id: str, from_seq: int = 0) -> AsyncIterator[Event]: ...

    async def read(self, mission_id: str, from_seq: int = 0, to_seq: int | None = None) -> list[Event]: ...


class Blackboard(Protocol):
    """Projection of events into a Mission aggregate. All mutations go through ``emit``."""

    mission: Mission

    async def emit(self, type: EventType, actor: str, payload: dict[str, Any], **kw: Any) -> Event: ...

    def snapshot(self, at_seq: int | None = None) -> Mission:
        """Time travel: rebuild state as of ``at_seq`` (UI scrubber, resume)."""
        ...


# --------------------------------------------------------------------------------------
# Tools & execution
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class ToolContext:
    mission_id: str
    agent_id: str
    mode_id: str
    task_key: str | None
    workspace_ref: str  # 'main' | 'cand-A' | 'baseline'
    allowed_tools: frozenset[str]
    may_edit_tests: bool = False
    file_locks: frozenset[str] = frozenset()


@dataclass(slots=True)
class ToolResult:
    ok: bool
    tool: str
    output: str
    evidence_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    fallback_used: str | None = None
    truncated: bool = False
    structured: dict[str, Any] = field(default_factory=dict)

    def for_model(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "tool": self.tool, "evidence_id": self.evidence_id}
        if self.error_code:
            out["error"] = {"code": self.error_code, "message": self.error_message,
                            "fallback_used": self.fallback_used}
        out["output"] = self.output
        out["truncated"] = self.truncated
        return out


class Tool(Protocol):
    name: str  # dotted display name, e.g. "fs.edit"
    schema: ToolSchema
    evidence_kind: EvidenceKind

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult: ...


class ToolGateway(Protocol):
    async def execute(self, ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult: ...

    def schemas(self, tool_names: Sequence[str]) -> list[ToolSchema]: ...


@dataclass(slots=True)
class ExecResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


class Executor(Protocol):
    """LocalExecutor (subprocess, scrubbed env) or DockerExecutor (--network none)."""

    async def run(self, argv: list[str], cwd: Path, timeout_s: int, env: dict[str, str] | None = None) -> ExecResult: ...


class Workspaces(Protocol):
    """Git worktree manager. 'main' is the mission worktree; candidates and baseline are siblings."""

    async def create_main(self, repo: Path, mission_id: str) -> Path: ...
    async def create_baseline(self) -> Path: ...
    async def fork(self, name: str, from_ref: str = "main") -> Path: ...
    async def path(self, ref: str) -> Path: ...
    async def tree_sha(self, ref: str = "main") -> str: ...
    async def diff(self, ref: str = "main", against: str = "baseline") -> str: ...
    async def hunks(self, ref: str = "main") -> list[dict[str, Any]]: ...
    async def checkpoint(self, label: str, ref: str = "main") -> str: ...
    async def rollback(self, sha: str, ref: str = "main") -> None: ...
    async def adopt(self, candidate: str) -> None:
        """Make candidate worktree content the new 'main' state (tournament winner)."""
        ...
    async def apply_to_target(self) -> str:
        """ff-merge mission branch into target repo. Refuses on dirty target. Human-gated by caller."""
        ...


class EvidenceLedger(Protocol):
    async def record(self, ev: Evidence, raw_output: str) -> Evidence: ...
    def get(self, evidence_id: str) -> Evidence: ...
    def exists(self, evidence_id: str) -> bool: ...


# --------------------------------------------------------------------------------------
# Deterministic analysis services
# --------------------------------------------------------------------------------------


class RepoIntelService(Protocol):
    async def build(self, workspace: Path, request: str) -> RepoIntel: ...
    async def rerank(self, query: str, k: int = 40) -> list[dict[str, Any]]: ...
    def callers_of(self, qualname: str) -> list[str]: ...
    def tests_covering(self, path: str, lines: Sequence[int]) -> list[str]: ...


class TestRunner(Protocol):
    async def run(
        self,
        scope: Literal["targeted", "full", "acceptance", "probe", "baseline"],
        workspace_ref: str = "main",
        selectors: Sequence[str] = (),
        ctx: ToolContext | None = None,
    ) -> TestRun: ...

    async def rerun_isolated(self, nodeid: str, times: int = 2, workspace_ref: str = "main") -> list[bool]: ...


class DeltaDebugger(Protocol):
    async def isolate(self, failing_nodeids: Sequence[str]) -> dict[str, Any]:
        """ddmin over diff hunks in a scratch worktree → {'culprit_hunks': [...], 'evidence_id': ...}."""
        ...


class VerificationLab(Protocol):
    """Advanced checks used by the Verifier (exposed to it as tools)."""

    async def differential(self, module: str, func: str, inputs_py: str) -> ToolResult: ...
    async def property_test(self, test_source: str) -> ToolResult: ...
    async def mutation(self, changed_only: bool = True, max_mutants: int = 40) -> ToolResult: ...
    async def changed_line_coverage(self) -> ToolResult: ...
    async def test_integrity(self) -> ToolResult: ...


class SecurityLab(Protocol):
    async def secrets(self, scope: Literal["diff", "repo"]) -> ToolResult: ...
    async def sast(self, paths: Sequence[str]) -> ToolResult: ...
    async def taint(self, paths: Sequence[str]) -> ToolResult: ...


# --------------------------------------------------------------------------------------
# Memory & human
# --------------------------------------------------------------------------------------


class MemoryStore(Protocol):
    async def recall(self, repo_key: str, query: str, kinds: Sequence[str], k: int = 5) -> list[MemoryItem]: ...
    async def write(self, item: MemoryItem) -> None: ...
    async def reinforce(self, item_id: str, delta: float) -> None: ...


class HumanChannel(Protocol):
    """UI (WebSocket), CLI prompt, or answers file. ``ask`` blocks until answered."""

    async def ask(self, prompt: HumanPrompt) -> HumanDecision: ...


# --------------------------------------------------------------------------------------
# Agent runtime
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class ModeInvocation:
    mode_id: str
    agent_id: str
    task_key: str | None = None
    attempt: int | None = None
    workspace_ref: str = "main"
    extra_context: dict[str, Any] = field(default_factory=dict)  # e.g. strategy_hint, lens, dossier
    tier_override: ModelTier | None = None


@runtime_checkable
class AgentRuntime(Protocol):
    async def invoke(self, inv: ModeInvocation) -> BaseModel:
        """Run one mode to completion; returns the validated LLMOutput (also recorded as Submission)."""
        ...
