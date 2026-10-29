"""Rich live view of a running mission: header + phase stepper, budget line, tasks, timeline, active modes.

The view is a pure function of the mission aggregate plus the events it has been fed, so it can be
rendered (and tested) without a terminal. Output is ASCII-only markers (``[x] [>] [ ]``) so that status
is readable on any console and never depends on colour alone.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from devpilot.core.events import Event, EventType
from devpilot.core.models import Mission, MissionStatus

# docs/12-MISSION-CONTROL-UI.md section 9
AGENT_COLOURS: dict[str, str] = {
    "shogun": "#E34234",
    "scout": "#4FA3E0",
    "samurai": "#D4A84B",
    "sentinel": "#3FB27F",
    "verifier": "#A78BFA",
    "reviewer": "#F472B6",
    "security": "#94A3B8",
    "human": "#FFFFFF",
}

PHASES: tuple[MissionStatus, ...] = (
    MissionStatus.INTEL,
    MissionStatus.RECON,
    MissionStatus.ANALYZING,
    MissionStatus.PLANNING,
    MissionStatus.AUTHORING_ACCEPTANCE,
    MissionStatus.EXECUTING,
    MissionStatus.TESTING,
    MissionStatus.CHECKING,
    MissionStatus.AWAITING_APPLY,
    MissionStatus.APPLYING,
    MissionStatus.REPORTING,
)
_PHASE_SHORT = {
    MissionStatus.AUTHORING_ACCEPTANCE: "ACCEPT",
    MissionStatus.AWAITING_APPLY: "GATE",
    MissionStatus.APPLYING: "APPLY",
    MissionStatus.REPORTING: "REPORT",
    MissionStatus.ANALYZING: "ANALYZE",
    MissionStatus.PLANNING: "PLAN",
}
# statuses that sit between two stepper phases map onto the nearest one
_PHASE_ALIAS = {
    MissionStatus.CLARIFYING: MissionStatus.ANALYZING,
    MissionStatus.AWAITING_PLAN_APPROVAL: MissionStatus.PLANNING,
    MissionStatus.DECIDING: MissionStatus.TESTING,
}
_STATUS_STYLE = {
    MissionStatus.COMPLETED_VERIFIED: "bold green",
    MissionStatus.COMPLETED_PARTIAL: "bold yellow",
    MissionStatus.FAILED: "bold red",
    MissionStatus.ABORTED: "bold red",
}
TIMELINE_LINES = 15
_QUIET_TYPES = frozenset({EventType.AGENT_TEXT_DELTA})


def agent_colour(actor: str) -> str:
    return AGENT_COLOURS.get(actor.split("#", 1)[0].lower(), "#8A8F98")


def phase_stepper(status: MissionStatus) -> Text:
    """``[x] INTEL  [>] RECON  [ ] ...`` with the current phase highlighted."""
    status = _PHASE_ALIAS.get(status, status)
    done = status.terminal
    cur = PHASES.index(status) if status in PHASES else -1
    out = Text()
    for i, ph in enumerate(PHASES):
        label = _PHASE_SHORT.get(ph, ph.value)
        if done or i < cur:
            out.append(f"[x] {label}  ", style="green")
        elif i == cur:
            out.append(f"[>] {label}  ", style="bold #E34234")
        else:
            out.append(f"[ ] {label}  ", style="dim")
    return out


class MissionView:
    """Accumulates events and renders the dashboard."""

    def __init__(
        self,
        mission: Mission,
        *,
        model_for: Callable[[str], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mission = mission
        self._model_for = model_for
        self._clock = clock
        self._t0 = clock()
        self.timeline: deque[Event] = deque(maxlen=TIMELINE_LINES)
        self.active: dict[str, tuple[str, str]] = {}  # actor -> (mode_id, model)

    def feed(self, ev: Event) -> None:
        if ev.type in _QUIET_TYPES:
            return
        self.timeline.append(ev)
        if ev.type == EventType.MODE_STARTED:
            model = str(ev.payload.get("model") or "")
            if not model and self._model_for is not None and ev.mode_id:
                model = self._model_for(ev.mode_id)
            self.active[ev.actor] = (ev.mode_id or str(ev.payload.get("mode", "")), model)
        elif ev.type in (EventType.MODE_FINISHED, EventType.MODE_FAILED):
            self.active.pop(ev.actor, None)

    # ------------------------------------------------------------------------------------------

    def _header(self) -> RenderableType:
        m = self.mission
        title = Text()
        title.append(f"DevPilot  {m.id}  ", style="bold")
        title.append(f"[{m.status.value}]", style=_STATUS_STYLE.get(m.status, "bold #D4A84B"))
        return Panel(Group(title, phase_stepper(m.status)), title="mission", border_style="#8A8F98")

    def _budget(self) -> Text:
        b = self.mission.budget
        lim = b.limits
        elapsed = self._clock() - self._t0
        return Text(
            f"tokens {b.tokens_in + b.tokens_out:,}/{lim.max_tokens_mission:,}  "
            f"cost ${b.cost_usd:.2f}/${lim.max_cost_usd:.2f}  "
            f"fix cycles {b.fix_cycles}/{lim.max_fix_cycles}  "
            f"tools {b.tool_calls}  elapsed {int(elapsed // 60)}m{int(elapsed % 60):02d}s",
            style="#D4A84B",
        )

    def _tasks(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", expand=True, box=None)
        for col in ("task", "status", "who", "attempts", "title"):
            table.add_column(col, overflow="ellipsis", no_wrap=True)
        for t in self.mission.tasks.values():
            who = t.assignee or "-"
            table.add_row(
                t.key,
                Text(t.status.value, style="green" if t.status.value == "DONE" else ""),
                Text(who, style=agent_colour(who)),
                str(len(t.attempts)),
                t.title,
            )
        if not self.mission.tasks:
            table.add_row("-", "no plan yet", "", "", "")
        return Panel(table, title="plan", border_style="#8A8F98")

    def _timeline(self) -> RenderableType:
        lines = Text(no_wrap=True, overflow="ellipsis")
        if not self.timeline:
            lines.append("waiting for events...", style="dim")
        for ev in self.timeline:
            who = ev.actor
            lines.append(f"{ev.seq:>4} ", style="dim")
            lines.append(f"{who:<11}", style=agent_colour(who))
            lines.append(f"{ev.type.value:<18}", style="dim")
            lines.append((ev.summary or "")[:90] + "\n")
        return Panel(lines, title="timeline", border_style="#8A8F98")

    def _active(self) -> Text:
        if not self.active:
            return Text("active: idle", style="dim")
        out = Text("active: ")
        for actor, (mode, model) in self.active.items():
            out.append(f"{actor} ", style=agent_colour(actor))
            out.append(f"{mode}" + (f" ({model})" if model else "") + "   ")
        return out

    def render(self) -> RenderableType:
        return Group(self._header(), self._budget(), self._tasks(), self._timeline(), self._active())
