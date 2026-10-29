"""DevPilot command-line interface: ``run`` (live terminal mission), ``doctor``, ``events``, ``modes``.

Exit codes of ``run``: 0 verified, 2 partial, 3 failed, 130 aborted/Ctrl-C; 64 usage (single-agent not
wired), 66 bad repo path, 69 required component missing, 78 configuration (no API key / bad answers).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from devpilot import wiring
from devpilot.cli_view import MissionView, agent_colour
from devpilot.config import get_anthropic_api_key, load_settings
from devpilot.core.events import Event, EventType
from devpilot.core.models import MissionStatus
from devpilot.engine import modes as mode_registry
from devpilot.human import AnswersFileError, AnswersFileHumanChannel, ConsoleHumanChannel
from devpilot.state.event_store import EVENTS_FILENAME, read_events_sync

app = typer.Typer(
    name="devpilot",
    help="DevPilot - Autonomous Multi-Agent AI Engineering Guild",
    no_args_is_help=True,
)

EXIT_PARTIAL = 2
EXIT_FAILED = 3
EXIT_USAGE = 64
EXIT_NOREPO = 66
EXIT_MISSING = 69
EXIT_CONFIG = 78
EXIT_ABORTED = 130

_EXIT_BY_STATUS = {
    MissionStatus.COMPLETED_VERIFIED: 0,
    MissionStatus.COMPLETED_PARTIAL: EXIT_PARTIAL,
    MissionStatus.FAILED: EXIT_FAILED,
    MissionStatus.ABORTED: EXIT_ABORTED,
}


def make_console() -> Console:
    """A Console that also works when stdout is a pipe on Windows (no legacy win32 writer)."""
    return Console(legacy_windows=False) if not sys.stdout.isatty() else Console()


def exit_code_for(status: MissionStatus) -> int:
    return _EXIT_BY_STATUS.get(status, EXIT_FAILED)


# --------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------


class LiveHolder:
    """Lets the console human channel suspend the Live display while it prompts."""

    def __init__(self) -> None:
        self.live: Live | None = None

    @contextlib.contextmanager
    def pause(self) -> Iterator[None]:
        live = self.live
        if live is None or not live.is_started:
            yield
            return
        live.stop()
        try:
            yield
        finally:
            live.start(refresh=True)


async def _pump(stack: wiring.MissionStack, view: MissionView, holder: LiveHolder, seen: list[int]) -> None:
    """Feed store events into the view and refresh the display."""
    async for ev in stack.store.subscribe(stack.mission_id):
        view.feed(ev)
        if ev.type != EventType.AGENT_TEXT_DELTA:
            seen[0] = max(seen[0], ev.seq)
        if holder.live is not None and holder.live.is_started:
            holder.live.update(view.render())


async def execute_mission(
    stack: wiring.MissionStack, console: Console, *, quiet: bool = False, holder: LiveHolder | None = None
) -> tuple[MissionStatus, bool]:
    """Run the orchestrator under the live view. Returns ``(final status, was_cancelled)``.

    Cancelling this coroutine (Ctrl-C) cancels the orchestrator, which finishes the mission ABORTED
    and writes its report before the cancellation completes.
    """
    holder = holder or LiveHolder()
    mission = stack.blackboard.mission

    def model_for(mode_id: str) -> str:
        try:
            return stack.settings.models.resolve_tier(mode_registry.get(mode_id).tier)
        except KeyError:
            return ""

    view = MissionView(mission, model_for=model_for)
    seen = [0]
    pump = asyncio.create_task(_pump(stack, view, holder, seen), name="live-view")
    orch = asyncio.create_task(stack.orchestrator.run(), name="orchestrator")
    cancelled = False
    live: Live | None = None
    if not quiet:
        live = Live(view.render(), console=console, refresh_per_second=4, transient=False)
        holder.live = live
        live.start()
    try:
        try:
            await orch
        except asyncio.CancelledError:
            cancelled = True
            orch.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await orch  # let the shielded ABORTED/report finish
        await stack.bridge.drain()
        for _ in range(40):  # let the view catch up with the last events
            if seen[0] >= mission.last_seq:
                break
            await asyncio.sleep(0.05)
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump
        if live is not None:
            live.update(view.render())
            live.stop()
            holder.live = None
    return mission.status, cancelled


def _print_summary(console: Console, stack: wiring.MissionStack, status: MissionStatus) -> None:
    m = stack.blackboard.mission
    style = {"COMPLETED_VERIFIED": "green", "COMPLETED_PARTIAL": "yellow"}.get(status.value, "red")
    lines = Text()
    lines.append(f"{status.value}\n", style=f"bold {style}")
    if m.outcome_reason:
        lines.append(f"{m.outcome_reason}\n")
    lines.append(f"events: {stack.store.path_for(stack.mission_id)}")
    console.print(Panel(lines, title=f"mission {m.id}"))


async def _run_async(
    *,
    repo: Path,
    request: str,
    mode: Literal["multi", "single"],
    profile: str,
    replay: Path | None,
    answers: Path | None,
    runs_dir: Path,
    quiet: bool,
    console: Console,
) -> int:
    settings = load_settings()
    try:
        settings.apply_profile(profile)
    except KeyError as exc:
        console.print(f"[red]{exc.args[0]}[/red]")
        return EXIT_USAGE
    holder = LiveHolder()
    human: ConsoleHumanChannel | AnswersFileHumanChannel
    try:
        human = (
            AnswersFileHumanChannel(answers)
            if answers is not None
            else ConsoleHumanChannel(console, pause=holder.pause)
        )
    except AnswersFileError as exc:
        console.print(f"[red]{exc}[/red]")
        return EXIT_CONFIG
    try:
        stack = await wiring.build_stack(
            settings,
            repo=repo,
            request=request,
            mode=mode,
            runs_dir=runs_dir,
            cassette=replay,
            cassette_mode="replay" if replay is not None else "record",
            answers=answers,
            human=human,
        )
    except wiring.WiringError as exc:
        console.print(f"[red]{exc}[/red]")
        return EXIT_CONFIG
    try:
        status, cancelled = await execute_mission(stack, console, quiet=quiet, holder=holder)
        _print_summary(console, stack, status)
    finally:
        await stack.shutdown()
    return EXIT_ABORTED if cancelled else exit_code_for(status)


@app.command()
def run(
    request: Annotated[str, typer.Argument(help="What you want done, in plain language.")],
    repo: Annotated[Path, typer.Option("--repo", help="Path of the repository to work on.")] = Path("."),
    mode: Annotated[str, typer.Option(help="multi (the guild) or single (baseline agent).")] = "multi",
    profile: Annotated[str, typer.Option(help="fast | balanced | careful")] = "balanced",
    replay: Annotated[Path | None, typer.Option(help="Replay LLM responses from a cassette file.")] = None,
    answers: Annotated[Path | None, typer.Option(help="JSON file answering the human gates.")] = None,
    runs_dir: Annotated[Path, typer.Option(help="Where mission data is stored.")] = Path("runs"),
    allow_missing: Annotated[
        bool, typer.Option("--allow-missing", help="Start even if parts are missing.")
    ] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="No live view; only the final summary.")] = False,
) -> None:
    """Run a mission against REPO with a live terminal view and human gates in the terminal."""
    console = make_console()
    if mode not in ("multi", "single"):
        console.print("[red]--mode must be 'multi' or 'single'[/red]")
        raise typer.Exit(EXIT_USAGE)
    if mode == "single":
        console.print("single-agent baseline not yet wired (WP-G14)")
        raise typer.Exit(EXIT_USAGE)
    if not repo.is_dir():
        console.print(f"[red]--repo {repo} is not a directory[/red]")
        raise typer.Exit(EXIT_NOREPO)
    present = wiring.probe_components()
    missing = [f"{name} ({wiring.packet_of(name)})" for name, ok in present.items() if not ok]
    if not present.get("test runner", False) and not allow_missing:
        console.print(
            "[red]Cannot start: no test runner is available.[/red]\n"
            f"Missing components: {', '.join(missing)}.\n"
            "A mission cannot verify anything without tests. Land those packets, or pass "
            "--allow-missing to start anyway (the mission will fail at its first test run)."
        )
        raise typer.Exit(EXIT_MISSING)
    if missing:
        console.print(f"[yellow]Running without: {', '.join(missing)}[/yellow]")
    if replay is None and answers is None and not sys.stdin.isatty():
        console.print("[yellow]stdin is not a terminal; human gates will reject on EOF.[/yellow]")
    code = asyncio.run(
        _run_async(
            repo=repo,
            request=request,
            mode="multi",
            profile=profile,
            replay=replay,
            answers=answers,
            runs_dir=runs_dir,
            quiet=quiet,
            console=console,
        )
    )
    raise typer.Exit(code)


# --------------------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------------------

_TOOL_FALLBACKS = {
    "git": "required: worktrees and diffs cannot work without it",
    "rg": "code search falls back to a pure-Python scan (slower)",
    "bandit": "SAST scan reports TOOL_UNAVAILABLE; the Security agent reviews by reading",
    "semgrep": "SAST scan reports TOOL_UNAVAILABLE; the Security agent reviews by reading",
    "docker": "sandbox tier 'worktree' (LocalExecutor, scrubbed env) is used",
}
_COMPONENT_FALLBACKS = {
    "tool registry": "every tool call returns TOOL_UNAVAILABLE; agents can only reason from their briefing",
    "test runner": "`devpilot run` refuses to start (override with --allow-missing; mission then fails)",
    "repo intel": "no repo map or caller graph; agents explore with fs/search tools",
    "delta debugger": "no hunk isolation of failures; triage relies on the test output",
}


def _tool_version(name: str) -> str:
    exe = shutil.which(name)
    if exe is None:
        if importlib.util.find_spec(name) is not None:
            return "python module"
        return ""
    try:
        res = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5, check=False)
        first = (res.stdout or res.stderr).strip().splitlines()
        return first[0][:60] if first else "found"
    except (OSError, subprocess.SubprocessError):
        return "found"


@app.command()
def doctor() -> None:
    """Check installed tools, credentials and which DevPilot components are available."""
    console = make_console()
    table = Table(title="DevPilot environment")
    for col in ("check", "status", "detail"):
        table.add_column(col)
    fallbacks: list[str] = []

    py = platform.python_version()
    py_ok = sys.version_info >= (3, 11)
    table.add_row("python", "ok" if py_ok else "FAIL", py)
    if not py_ok:
        fallbacks.append("python: 3.11+ is required")
    for tool in ("git", "rg", "bandit", "semgrep", "docker"):
        ver = _tool_version(tool)
        table.add_row(tool, "ok" if ver else "missing", ver or "-")
        if not ver:
            fallbacks.append(f"{tool}: {_TOOL_FALLBACKS[tool]}")
    key_set = bool(get_anthropic_api_key())  # presence only; the value is never printed
    table.add_row("ANTHROPIC_API_KEY", "set" if key_set else "missing", "-")
    if not key_set:
        fallbacks.append("ANTHROPIC_API_KEY: only `devpilot run --replay CASSETTE` can run")
    for name, ok in wiring.probe_components().items():
        table.add_row(name, "ok" if ok else "missing", "-" if ok else wiring.packet_of(name))
        if not ok:
            fallbacks.append(f"{name}: {_COMPONENT_FALLBACKS[name]}")
    console.print(table)
    if fallbacks:
        console.print("[bold]Fallbacks in effect[/bold]")
        for line in fallbacks:
            console.print(f"  - {line}", markup=False)
    if shutil.which("git") is None:
        raise typer.Exit(1)


# --------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------


def _event_line(ev: Event) -> Text:
    line = Text()
    line.append(f"{ev.seq:>5} ", style="dim")
    line.append(f"{ev.ts.strftime('%H:%M:%S')} ", style="dim")
    line.append(f"{ev.actor:<11}", style=agent_colour(ev.actor))
    line.append(f"{ev.type.value:<18}", style="bold")
    line.append(ev.summary)
    return line


@app.command()
def events(
    mission_id: Annotated[str, typer.Argument(help="Mission id, e.g. M-20260101-120000-ab12")],
    runs_dir: Annotated[Path, typer.Option(help="Where mission data is stored.")] = Path("runs"),
    type_: Annotated[str | None, typer.Option("--type", help="Only this event type.")] = None,
    follow: Annotated[
        bool, typer.Option("--follow", help="Keep printing new events until the mission ends.")
    ] = False,
) -> None:
    """Print a mission's timeline from its events.jsonl."""
    console = make_console()
    path = runs_dir / mission_id / EVENTS_FILENAME
    if not path.is_file():
        console.print(f"[red]no events file at {path}[/red]")
        raise typer.Exit(66)
    wanted = type_.upper() if type_ else None
    if wanted is not None and wanted not in EventType.__members__:
        console.print(f"[red]unknown event type {type_!r}[/red]")
        raise typer.Exit(EXIT_USAGE)
    seen = 0
    try:
        while True:
            batch = read_events_sync(path, seen + 1)
            for ev in batch:
                seen = ev.seq
                if wanted is None or ev.type.value == wanted:
                    console.print(_event_line(ev), soft_wrap=True)
            finished = any(e.type == EventType.MISSION_FINISHED for e in batch)
            if not follow or finished:
                return
            time.sleep(0.5)
    except KeyboardInterrupt:
        raise typer.Exit(EXIT_ABORTED) from None


# --------------------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------------------


@app.command()
def modes() -> None:
    """List the cognitive modes: agent, model tier, thinking budget, tools and hidden context."""
    console = make_console()
    table = Table(title="Cognitive modes")
    for col in ("mode", "agent", "tier", "thinking", "tools", "hidden slices"):
        table.add_column(col, overflow="fold")
    for spec in mode_registry.REGISTRY.values():
        thinking = str(spec.thinking.budget_tokens) if spec.thinking.enabled else "off"
        hidden = ", ".join(s.value for s in spec.context.hidden) or "-"
        table.add_row(
            Text(spec.id, overflow="fold"),
            spec.agent.value,
            spec.tier.value,
            thinking,
            str(len(spec.tools)),
            hidden,
        )
    console.print(table)


@app.command()
def demo() -> None:
    """Run reference demo mission."""
    typer.echo("Running DevPilot demo (FX2 Bug Investigation)...")
    typer.echo('Use: devpilot run --repo fixtures/fx2_bug_pagination "fix the pagination bug"')


if __name__ == "__main__":
    app()
