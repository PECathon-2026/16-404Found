"""Terminal human channel (rich panels). Never approves anything on its own.

* clarification / plan / dispute / scope / command: numbered options plus free text.
* escalation: provide guidance (type it), accept partial, or abort.
* apply: summary of ACs, tests, review/security, claims and files; ``d`` shows the diff. Approval
  needs the literal word ``approve``; if a must-priority AC is not VERIFIED the mission's short id must
  be typed as well. EOF on stdin is a rejection, never an approval.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Protocol

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from devpilot.core.models import ACStatus, HumanDecision, HumanPrompt, Mission
from devpilot.core.ports import Blackboard, Workspaces

InputFn = Callable[[str], str]

_STATUS_STYLE = {
    ACStatus.VERIFIED: "green",
    ACStatus.FAILED: "red",
}


class _GateExit(Exception):
    """stdin closed or the user interrupted a prompt."""


def short_id(mission_id: str) -> str:
    """The last dash-separated segment of ``M-YYYYMMDD-HHMMSS-abcd`` (the 4 hex chars)."""
    return mission_id.rsplit("-", 1)[-1]


class _Attachable(Protocol):
    def attach(self, workspaces: Workspaces, blackboard: Blackboard) -> None: ...


class ConsoleHumanChannel:
    """``ports.HumanChannel`` that prompts on the terminal."""

    def __init__(
        self,
        console: Console | None = None,
        *,
        input_fn: InputFn | None = None,
        pause: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        """``pause`` returns a context manager that suspends a rich Live display while we prompt."""
        self.console = console or Console()
        self._input: InputFn = input_fn or self.console.input
        self._pause = pause
        self.workspaces: Workspaces | None = None
        self.blackboard: Blackboard | None = None

    def attach(self, workspaces: Workspaces, blackboard: Blackboard) -> None:
        """Called by the composition root so the apply gate can read the mission and the diff."""
        self.workspaces = workspaces
        self.blackboard = blackboard

    # ------------------------------------------------------------------------------------------

    @contextlib.contextmanager
    def _suspended(self) -> Iterator[None]:
        if self._pause is None:
            yield
        else:
            with self._pause():
                yield

    async def _read(self, label: str) -> str:
        try:
            return (await asyncio.to_thread(self._input, label)).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise _GateExit from exc

    def _decision(self, prompt: HumanPrompt, choice: str | None, text: str | None = None) -> HumanDecision:
        return HumanDecision(
            id=f"HD-{prompt.id}", prompt_id=prompt.id, choice=choice, free_text=text or None, source="cli"
        )

    @staticmethod
    def _exit_choice(prompt: HumanPrompt) -> str | None:
        keys = {o.key for o in prompt.options}
        order = ("reject",) if prompt.gate == "apply" else ("abort", "cancel", "reject")
        return next((k for k in order if k in keys), None)

    async def ask(self, prompt: HumanPrompt) -> HumanDecision:
        with self._suspended():
            try:
                if prompt.gate == "apply":
                    return await self._apply_gate(prompt)
                return await self._generic_gate(prompt)
            except _GateExit:
                self.console.print("[yellow]input closed; not approving[/yellow]")
                return self._decision(prompt, self._exit_choice(prompt))

    # ------------------------------------------------------------------------------------------
    # generic gates
    # ------------------------------------------------------------------------------------------

    def _options_table(self, prompt: HumanPrompt) -> Table:
        table = Table(show_header=False, box=None, padding=(0, 1))
        for i, o in enumerate(prompt.options, 1):
            table.add_row(f"[bold]{i}[/bold]", f"[bold]{o.label}[/bold] ({o.key})", o.consequence)
        return table

    async def _generic_gate(self, prompt: HumanPrompt) -> HumanDecision:
        parts: list[RenderableType] = [Markdown(prompt.body_md)]
        if prompt.options:
            parts.append(self._options_table(prompt))
        self.console.print(Panel(Group(*parts), title=f"[bold]{prompt.title}[/bold]", subtitle=prompt.gate))
        n = len(prompt.options)
        hint = f"Choose 1-{n}" if n else "Answer"
        if prompt.allow_free_text:
            hint += " or type your own answer" if n else ""
        while True:
            raw = await self._read(f"{hint}: ")
            if not raw:
                self.console.print("[yellow]An answer is required.[/yellow]")
                continue
            choice = self._match_option(prompt, raw)
            if choice is not None:
                text: str | None = None
                if choice == "guidance":
                    text = await self._read("Your guidance: ") or None
                return self._decision(prompt, choice, text)
            if prompt.allow_free_text:
                return self._decision(prompt, None, raw)
            self.console.print("[yellow]Please pick one of the listed options.[/yellow]")

    @staticmethod
    def _match_option(prompt: HumanPrompt, raw: str) -> str | None:
        if raw.isdigit() and 1 <= int(raw) <= len(prompt.options):
            return prompt.options[int(raw) - 1].key
        low = raw.lower()
        return next((o.key for o in prompt.options if o.key.lower() == low), None)

    # ------------------------------------------------------------------------------------------
    # apply gate
    # ------------------------------------------------------------------------------------------

    def _ac_table(self, mission: Mission) -> Table:
        table = Table(title="Acceptance criteria", expand=False)
        for col in ("AC", "Priority", "Status", "Confidence", "Then"):
            table.add_column(col)
        for a in mission.acs:
            style = _STATUS_STYLE.get(a.status, "yellow")
            conf = f"{a.confidence:.2f}" if a.confidence is not None else "-"
            table.add_row(a.ac.id, a.ac.priority, Text(a.status.value, style=style), conf, a.ac.then[:70])
        return table

    @staticmethod
    def unmet_must(mission: Mission) -> list[str]:
        return [a.ac.id for a in mission.acs if a.ac.priority == "must" and a.status != ACStatus.VERIFIED]

    async def _show_diff(self) -> None:
        if self.workspaces is None:
            self.console.print("[yellow]No workspace attached; cannot show the diff.[/yellow]")
            return
        diff = await self.workspaces.diff()
        self.console.print(Syntax(diff or "(empty diff)", "diff", word_wrap=True))

    async def _apply_gate(self, prompt: HumanPrompt) -> HumanDecision:
        mission = self.blackboard.mission if self.blackboard is not None else None
        parts: list[RenderableType] = []
        if mission is not None and mission.acs:
            parts.append(self._ac_table(mission))
        parts.append(Markdown(prompt.body_md))
        unmet = self.unmet_must(mission) if mission is not None else []
        if unmet:
            parts.append(
                Text(f"WARNING: must-have criteria not VERIFIED: {', '.join(unmet)}", style="bold red")
            )
        self.console.print(Panel(Group(*parts), title=f"[bold]{prompt.title}[/bold]", subtitle="apply gate"))
        mid = mission.id if mission is not None else prompt.id
        while True:
            raw = await self._read(
                "Type 'approve' to apply, 'd' for the diff, 'c' to request changes, 'reject': "
            )
            low = raw.lower()
            if low == "d":
                await self._show_diff()
            elif low == "approve":
                if unmet:
                    typed = await self._read(
                        f"Not fully verified. Type the mission id ({short_id(mid)}) to confirm: "
                    )
                    if typed != short_id(mid):
                        self.console.print("[yellow]Mission id did not match; not approved.[/yellow]")
                        continue
                return self._decision(prompt, "approve")
            elif low in {"reject", "r", "n", "no"}:
                return self._decision(prompt, "reject")
            elif low in {"c", "changes"}:
                note = await self._read("What should change? ")
                if note:
                    return self._decision(prompt, "request_changes", note)
            else:
                self.console.print("[yellow]Nothing applied. Type exactly 'approve' to apply.[/yellow]")
