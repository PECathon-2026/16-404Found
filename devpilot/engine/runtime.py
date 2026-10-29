"""ModeRuntime: the one generic engine that executes any declared mode (``ports.AgentRuntime``).

Per invocation: resolve the ModeSpec -> assemble context -> compile a cache-friendly prompt -> loop
{LLM turn, tool calls, ``submit_*`` validation} until a valid submission, a refusal or a budget.

API constraints this loop cooperates with (see ``docs/llm-notes.md``):

* Opus/Sonnet 5.5 reject forced ``tool_choice``: we only force the submit tool after the model has ended
  a turn without submitting, and we put the instruction text into *our own* history so it is permanent.
* History is append-only (preserved thinking): messages are never edited, dropped or reordered.
  Assistant turns are appended as ``raw_assistant_content`` verbatim.
* At most 4 cache breakpoints: we use exactly 3 (last tool, mode prompt, stable context block).
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import importlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from devpilot.config import Settings
from devpilot.core.events import EventType
from devpilot.core.models import LLMOutput, LLMUsage, ModelTier, Submission
from devpilot.core.ports import (
    Blackboard,
    LLMPort,
    LLMRequest,
    LLMResponse,
    ModeInvocation,
    PromptBlock,
    ToolContext,
    ToolGateway,
    ToolResult,
    ToolSchema,
    ToolUse,
)
from devpilot.engine import modes, validators
from devpilot.engine.context import AssembledContext, ContextAssembler, ContextServices
from devpilot.engine.errors import (
    BudgetExceeded,
    ModeFailed,
    ModeRefused,
    StepBudgetExceeded,
)
from devpilot.engine.modes import ModeSpec
from devpilot.llm import assert_append_only, needs_submit_instruction, submit_instruction

log = logging.getLogger(__name__)

MAX_NUDGES = 2
DELTA_FLUSH_INTERVAL_S = 0.05  # ~20 events/s
TEXT_EXCERPT_CHARS = 500
MAX_TOKENS_CONTINUE = "Your previous output was cut off by the length limit. Continue, more concisely."

# Tools with side effects: run one at a time in the model's order. Everything else may run concurrently.
SEQUENTIAL_TOOLS: frozenset[str] = frozenset(
    {"fs.edit", "fs.write", "fs.write_probe", "shell.run", "test.run", "test.rerun", "msg.send"}
)
# Tool results that are system-generated acknowledgements rather than repo-derived text: not fenced.
UNFENCED_TOOLS: frozenset[str] = frozenset({"fs.edit", "fs.write", "fs.write_probe", "msg.send"})

PromptSource = Callable[[str], str]


def display_name(api_name: str) -> str:
    """``fs_edit`` -> ``fs.edit`` (the gateway's API-safe names replace the first dot with ``_``)."""
    return api_name.replace("_", ".", 1) if "." not in api_name else api_name


def _default_prompt_source(mode_id: str) -> str:
    mod = importlib.import_module("devpilot.prompts")
    return str(mod.load_mode_prompt(mode_id))


def _default_constitution() -> str:
    mod = importlib.import_module("devpilot.prompts")
    return str(mod.load_constitution())


@dataclasses.dataclass(slots=True)
class _Run:
    """Mutable per-invocation state."""

    spec: ModeSpec
    inv: ModeInvocation
    tier: ModelTier
    thinking_budget: int | None
    model: str
    system: list[PromptBlock]
    tools: list[ToolSchema]
    messages: list[dict[str, Any]]
    usages: list[LLMUsage] = dataclasses.field(default_factory=list)
    thinking: list[str] = dataclasses.field(default_factory=list)
    tool_choice: dict[str, Any] | None = None
    repairs: int = 0
    nudges: int = 0
    sent: list[dict[str, Any]] | None = None


class ModeRuntime:
    """``ports.AgentRuntime`` implementation. One instance may serve many concurrent invocations."""

    def __init__(
        self,
        blackboard: Blackboard,
        llm: LLMPort,
        gateway: ToolGateway,
        services: ContextServices,
        settings: Settings,
        *,
        prompt_source: PromptSource | None = None,
        constitution: Callable[[], str] | None = None,
        debug: bool = False,
        validation_hooks: dict[str, Callable[..., Any]] | None = None,
        spec_lookup: Callable[[str], ModeSpec] = modes.get,
    ) -> None:
        """``validation_hooks`` may supply ``diff_names``, ``collect_tests``, ``hunk_paths``,
        ``path_exists`` (async) and ``evidence_exists`` (sync ledger lookup); they override the defaults
        derived from ``services.workspaces``. ``spec_lookup`` exists for tests."""
        self.blackboard = blackboard
        self.llm = llm
        self.gateway = gateway
        self.services = services
        self.settings = settings
        self._prompt_source = prompt_source or _default_prompt_source
        self._constitution = constitution or _default_constitution
        self.debug = debug
        self._hooks = validation_hooks or {}
        self._spec_lookup = spec_lookup
        self._assembler = ContextAssembler()

    # ------------------------------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------------------------------

    async def invoke(self, inv: ModeInvocation) -> LLMOutput:
        """Run one mode to completion and return its validated, recorded output."""
        spec = self._spec_lookup(inv.mode_id)
        run = await self._start(spec, inv)
        try:
            async with asyncio.timeout(spec.limits.wall_clock_s):
                return await self._loop(run)
        except TimeoutError:
            reason = f"wall clock of {spec.limits.wall_clock_s}s exceeded"
            await self._emit_failed(run, reason, "wall_clock")
            raise ModeFailed(spec.id, reason) from None

    # ------------------------------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------------------------------

    def _resolve_tier(self, spec: ModeSpec, inv: ModeInvocation) -> tuple[ModelTier, int | None, bool]:
        budget: int | None = spec.thinking.budget_tokens if spec.thinking.enabled else None
        if inv.tier_override is not None:
            return inv.tier_override, budget, False
        esc = spec.escalation
        if esc is not None and (inv.attempt or 1) >= esc.on_attempt:
            return esc.to, esc.thinking_budget, esc.to != spec.tier
        return spec.tier, budget, False

    async def _start(self, spec: ModeSpec, inv: ModeInvocation) -> _Run:
        bb = self.blackboard
        mission = bb.mission
        tier, thinking_budget, escalated = self._resolve_tier(spec, inv)
        model = self.llm.resolve(tier)
        ctx = await self._assembler.assemble(spec, mission, inv, self.services)
        if escalated:
            await self._emit(
                inv,
                spec,
                EventType.MODEL_ESCALATED,
                {
                    "mode": spec.id,
                    "from_tier": spec.tier,
                    "to_tier": tier,
                    "model": model,
                    "attempt": inv.attempt,
                    "thinking_budget": thinking_budget,
                },
                summary=f"{spec.id} escalated {spec.tier.value} -> {tier.value} on attempt {inv.attempt}",
            )
        await self._emit(
            inv,
            spec,
            EventType.MODE_STARTED,
            {
                "mode": spec.id,
                "agent": spec.agent,
                "task": inv.task_key,
                "attempt": inv.attempt,
                "model": model,
                "tier": tier,
                "thinking_budget": thinking_budget,
                "tools": list(spec.tools),
                "included": ctx.included,
                "hidden": ctx.hidden,
                "token_estimates": ctx.token_estimates,
            },
            summary=f"{spec.id} started on {model}",
        )
        return _Run(
            spec=spec,
            inv=inv,
            tier=tier,
            thinking_budget=thinking_budget,
            model=model,
            system=[
                PromptBlock(self._constitution(), cache=False),
                PromptBlock(self._prompt_source(spec.id), cache=True),
            ],
            tools=self._compile_tools(spec),
            messages=[{"role": "user", "content": self._first_message(ctx)}],
        )

    def _compile_tools(self, spec: ModeSpec) -> list[ToolSchema]:
        tools = [dataclasses.replace(t, cache=False) for t in self.gateway.schemas(list(spec.tools))]
        tools.append(
            ToolSchema(
                name=spec.submit_tool,
                description=(
                    f"Submit your final {spec.output.__name__} for mode {spec.id}. Call this exactly once, "
                    "when your work is complete; the call ends the task."
                ),
                input_schema=spec.output.model_json_schema(),
                cache=True,
            )
        )
        return tools

    @staticmethod
    def _first_message(ctx: AssembledContext) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        if ctx.stable.strip():
            blocks.append({"type": "text", "text": ctx.stable, "cache_control": {"type": "ephemeral"}})
        if ctx.volatile.strip():
            blocks.append({"type": "text", "text": ctx.volatile})
        return blocks or [{"type": "text", "text": "Begin."}]

    # ------------------------------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------------------------------

    async def _emit(
        self,
        inv: ModeInvocation,
        spec: ModeSpec,
        type_: EventType,
        payload: dict[str, Any],
        summary: str = "",
    ) -> None:
        await self.blackboard.emit(
            type_, inv.agent_id, payload, mode_id=spec.id, task_key=inv.task_key, summary=summary
        )

    async def _emit_failed(self, run: _Run, reason: str, kind: str) -> None:
        await self._emit(
            run.inv,
            run.spec,
            EventType.MODE_FAILED,
            {"mode": run.spec.id, "reason": reason, "kind": kind, "task": run.inv.task_key},
            summary=f"{run.spec.id} failed: {reason}",
        )

    # ------------------------------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------------------------------

    async def _loop(self, run: _Run) -> LLMOutput:
        spec, inv = run.spec, run.inv
        for _ in range(spec.limits.max_steps):
            mission = self.blackboard.mission
            if mission.budget.ratio() >= 1.0:
                reason = f"mission budget exhausted (ratio {mission.budget.ratio():.2f})"
                await self._emit(
                    inv, spec, EventType.BUDGET_EXCEEDED, {"ratio": mission.budget.ratio()}, reason
                )
                await self._emit_failed(run, reason, "budget")
                raise BudgetExceeded(spec.id, reason)

            resp = await self._turn(run)

            if resp.stop_reason == "refusal":
                await self._emit_failed(run, "model refused", "refusal")
                raise ModeRefused(spec.id, "model refused to continue")

            run.messages.append({"role": "assistant", "content": resp.raw_assistant_content})

            if resp.stop_reason == "max_tokens":
                run.messages.append(self._cut_off_message(resp))
                continue

            if not resp.tool_uses:
                await self._nudge(run)
                continue

            out = await self._handle_tools(run, resp.tool_uses)
            if out is not None:
                return out

        reason = f"no valid submission within {spec.limits.max_steps} steps"
        await self._emit_failed(run, reason, "steps")
        raise StepBudgetExceeded(spec.id, reason)

    async def _turn(self, run: _Run) -> LLMResponse:
        """One model call: append the submit instruction if needed, stream, record usage."""
        spec, inv = run.spec, run.inv
        req = LLMRequest(
            tier=run.tier,
            system=run.system,
            messages=list(run.messages),  # shallow copy: callers/fakes may keep the request
            tools=run.tools,
            tool_choice=run.tool_choice,
            thinking_budget=run.thinking_budget,
            max_output_tokens=spec.limits.max_output_tokens,
            metadata={
                "mission_id": self.blackboard.mission.id,
                "mode": spec.id,
                "agent": inv.agent_id,
                "task": inv.task_key,
            },
        )
        if needs_submit_instruction(req, run.model) and not self._ends_with_instruction(run):
            run.messages.append({"role": "user", "content": [submit_instruction(spec.submit_tool)]})
            req.messages = list(run.messages)
        if self.debug and run.sent is not None:
            assert_append_only(run.sent, run.messages)
        if self.debug:
            run.sent = copy.deepcopy(run.messages)

        final: LLMResponse | None = None
        buf: list[str] = []
        last_flush = time.monotonic()
        async for item in self.llm.stream(req):
            if isinstance(item, str):
                buf.append(item)
                now = time.monotonic()
                if now - last_flush >= DELTA_FLUSH_INTERVAL_S:
                    await self._flush(run, buf)
                    last_flush = now
            else:
                final = item
        await self._flush(run, buf)
        if final is None:
            raise ModeFailed(spec.id, "LLM stream ended without a final response")

        run.usages.append(final.usage)
        if final.thinking_summary:
            run.thinking.append(final.thinking_summary)
        await self._emit(
            inv,
            spec,
            EventType.LLM_TURN,
            {
                "usage": final.usage,
                "thinking_summary": final.thinking_summary,
                "text_excerpt": final.text[:TEXT_EXCERPT_CHARS],
                "stop_reason": final.stop_reason,
            },
            summary=f"{spec.id} turn: {final.stop_reason}",
        )
        return final

    async def _flush(self, run: _Run, buf: list[str]) -> None:
        if buf:
            delta = "".join(buf)
            buf.clear()
            await self._emit(run.inv, run.spec, EventType.AGENT_TEXT_DELTA, {"delta": delta})

    def _ends_with_instruction(self, run: _Run) -> bool:
        last = run.messages[-1]
        content = last.get("content")
        marker = submit_instruction(run.spec.submit_tool)
        return last.get("role") == "user" and isinstance(content, list) and marker in content

    async def _nudge(self, run: _Run) -> None:
        """The model ended a turn without submitting: say so (permanently) and force the submit tool."""
        run.nudges += 1
        if run.nudges > MAX_NUDGES:
            reason = f"model ended its turn without calling {run.spec.submit_tool} after {MAX_NUDGES} nudges"
            await self._emit_failed(run, reason, "no_submit")
            raise ModeFailed(run.spec.id, reason)
        run.messages.append({"role": "user", "content": [submit_instruction(run.spec.submit_tool)]})
        run.tool_choice = {"type": "tool", "name": run.spec.submit_tool}

    @staticmethod
    def _cut_off_message(resp: LLMResponse) -> dict[str, Any]:
        """User message after a max_tokens turn; truncated tool_use blocks must still get a tool_result."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "tool_result",
                "tool_use_id": tu.id,
                "is_error": True,
                "content": "Your output was cut off by the length limit before this call completed; it was not run.",
            }
            for tu in resp.tool_uses
        ]
        blocks.append({"type": "text", "text": MAX_TOKENS_CONTINUE})
        return {"role": "user", "content": blocks}

    # ------------------------------------------------------------------------------------------
    # tools & submission
    # ------------------------------------------------------------------------------------------

    def _tool_context(self, run: _Run) -> ToolContext:
        inv = run.inv
        task = self.blackboard.mission.tasks.get(inv.task_key) if inv.task_key else None
        return ToolContext(
            mission_id=self.blackboard.mission.id,
            agent_id=inv.agent_id,
            mode_id=run.spec.id,
            task_key=inv.task_key,
            workspace_ref=inv.workspace_ref,
            allowed_tools=frozenset(run.spec.tools),
            may_edit_tests=task.may_edit_tests if task else False,
            file_locks=frozenset(task.files_to_touch) if task else frozenset(),
        )

    async def _handle_tools(self, run: _Run, uses: list[ToolUse]) -> LLMOutput | None:
        """Run the turn's tool calls, validate any submit, and append ONE user message of results."""
        submit_name = run.spec.submit_tool
        submits = [u for u in uses if u.name == submit_name]
        others = [u for u in uses if u.name != submit_name]
        results: dict[str, dict[str, Any]] = {}

        ctx = self._tool_context(run)
        for u, block in zip(others, await self._run_tools(ctx, others), strict=True):
            results[u.id] = block

        accepted: LLMOutput | None = None
        for i, u in enumerate(submits):
            if i > 0:
                results[u.id] = self._error_block(u.id, "Call the submit tool only once per turn.")
                continue
            output, errors = await self._validate(run, u.input)
            if output is not None and not errors:
                accepted = output
                results[u.id] = {
                    "type": "tool_result",
                    "tool_use_id": u.id,
                    "content": "Submission accepted.",
                }
            else:
                detail = "\n".join(f"- {e}" for e in errors)
                results[u.id] = self._error_block(u.id, f"Submission rejected:\n{detail}")

        if accepted is not None:
            await self._record(run, accepted)
            return accepted

        if submits:
            run.repairs += 1
            if run.repairs > run.spec.limits.max_repair_rounds:
                reason = f"submission still invalid after {run.spec.limits.max_repair_rounds} repair rounds"
                await self._emit_failed(run, reason, "repair")
                raise ModeFailed(run.spec.id, reason)
        run.messages.append({"role": "user", "content": [results[u.id] for u in uses]})
        return None

    @staticmethod
    def _error_block(tool_use_id: str, message: str) -> dict[str, Any]:
        return {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": message}

    async def _run_tools(self, ctx: ToolContext, uses: list[ToolUse]) -> list[dict[str, Any]]:
        """Execute calls: consecutive read-only calls concurrently, side-effecting ones in order."""
        blocks: list[dict[str, Any] | None] = [None] * len(uses)
        i = 0
        while i < len(uses):
            if display_name(uses[i].name) in SEQUENTIAL_TOOLS:
                blocks[i] = await self._exec_one(ctx, uses[i])
                i += 1
                continue
            j = i
            while j < len(uses) and display_name(uses[j].name) not in SEQUENTIAL_TOOLS:
                j += 1
            batch = await asyncio.gather(*(self._exec_one(ctx, u) for u in uses[i:j]))
            blocks[i:j] = batch
            i = j
        return [b for b in blocks if b is not None]

    async def _exec_one(self, ctx: ToolContext, use: ToolUse) -> dict[str, Any]:
        try:
            res = await self.gateway.execute(ctx, use.name, use.input)
        except Exception as exc:  # the gateway should not raise; never let a tool crash the loop
            log.exception("gateway raised for %s", use.name)
            res = ToolResult(
                ok=False, tool=use.name, output="", error_code="GATEWAY_ERROR", error_message=str(exc)
            )
        text = json.dumps(res.for_model(), default=str)
        if display_name(use.name) not in UNFENCED_TOOLS:
            text = f'<untrusted source="tool:{display_name(use.name)}">{text}</untrusted>'
        return {"type": "tool_result", "tool_use_id": use.id, "content": text, "is_error": not res.ok}

    # ------------------------------------------------------------------------------------------
    # validation & recording
    # ------------------------------------------------------------------------------------------

    def _validation_context(self, run: _Run) -> validators.ValidationContext:
        ws = self.services.workspaces
        ref = run.inv.workspace_ref
        hooks = self._hooks

        async def diff_names() -> list[str]:
            assert ws is not None
            return validators.parse_diff_names(await ws.diff(ref))

        async def hunk_paths() -> list[str]:
            assert ws is not None
            out: list[str] = []
            for h in await ws.hunks(ref):
                path = h.get("path") or h.get("file")
                lo = h.get("new_start", h.get("start", h.get("line_start")))
                n = h.get("new_lines", h.get("lines"))
                hi = h.get("line_end", (lo + max(int(n), 1) - 1) if lo is not None and n is not None else lo)
                if path and lo is not None:
                    out.append(f"{path}:L{lo}-L{hi}")
            return out

        async def path_exists(rel: str) -> bool:
            assert ws is not None
            root = Path(await ws.path(ref))
            return await asyncio.to_thread((root / rel).exists)

        have_ws = ws is not None
        return validators.ValidationContext(
            mission=self.blackboard.mission,
            inv=run.inv,
            ledger_exists=hooks.get("evidence_exists"),
            diff_names=hooks.get("diff_names") or (diff_names if have_ws else None),
            collect_tests=hooks.get("collect_tests"),
            hunk_paths=hooks.get("hunk_paths") or (hunk_paths if have_ws else None),
            path_exists=hooks.get("path_exists") or (path_exists if have_ws else None),
        )

    async def _validate(self, run: _Run, payload: dict[str, Any]) -> tuple[LLMOutput | None, list[str]]:
        """Schema validation, then the spec's semantic validators. Returns (instance, errors)."""
        try:
            out = run.spec.output.model_validate(payload)
        except ValidationError as exc:
            return None, [
                f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
            ]
        vctx = self._validation_context(run)
        errors: list[str] = []
        for name in run.spec.validators:
            try:
                errors += await validators.VALIDATORS[name](out, vctx)
            except Exception as exc:  # a crashing validator must not wedge or silently pass the mode
                log.exception("validator %s crashed", name)
                errors.append(f"internal validator error in {name}: {exc}")
        return out, errors

    async def _record(self, run: _Run, out: LLMOutput) -> None:
        spec, inv = run.spec, run.inv
        sub = Submission(
            id=f"S-{uuid.uuid4().hex[:8]}",
            mode_id=spec.id,
            agent_id=inv.agent_id,
            model=run.model,
            task_key=inv.task_key,
            attempt=inv.attempt,
            output_type=spec.output.__name__,
            payload=out.model_dump(mode="json"),
            usage=run.usages,
            thinking_summary="\n\n".join(run.thinking) or None,
        )
        await self._emit(
            inv,
            spec,
            EventType.SUBMISSION,
            {"submission": sub},
            summary=f"{spec.id} submitted {sub.output_type}",
        )
        await self._emit(
            inv,
            spec,
            EventType.MODE_FINISHED,
            {"mode": spec.id, "submission_id": sub.id, "steps": len(run.usages), "task": inv.task_key},
            summary=f"{spec.id} finished",
        )
