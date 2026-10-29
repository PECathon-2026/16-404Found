"""Write ``REPORT.md``, ``report.html``, ``mission.json`` and ``final.diff`` for a mission.

``make_report_writer`` returns the ``Callable[[Mission], Awaitable[None]]`` the orchestrator takes as
``report_writer``. This module never emits events: whoever wires the hook emits REPORT_WRITTEN.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from devpilot.core.models import Mission
from devpilot.core.ports import EventStore, Workspaces
from devpilot.report.engine import (
    build_report,
    consistency_check,
    derive_final_tree_sha,
    parse_diff,
)
from devpilot.report.html import render_html
from devpilot.report.markdown import render_markdown

log = logging.getLogger(__name__)


class ReportConsistencyError(Exception):
    """The report claims something the evidence ledger does not support; nothing was written."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _atomic_write(path: Path, text: str) -> None:
    """Temp file in the same directory + rename, so readers never see a half-written report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


async def write_report(
    mission: Mission,
    store: EventStore,
    workspaces: Workspaces | None = None,
    *,
    out_dir: Path,
    force: bool = False,
) -> Path:
    """Build and write the report files into ``out_dir``; returns the path of ``REPORT.md``.

    Raises ``ReportConsistencyError`` (writing only ``REPORT_REFUSED.txt``) when the consistency check
    fails, unless ``force`` is set, in which case the report carries a red banner.
    """
    events = await store.read(mission.id)
    diff_text: str | None = None
    final_sha: str | None = None
    if workspaces is not None:
        try:
            diff_text = await workspaces.diff("main", "baseline")
        except Exception as exc:  # a missing diff degrades the report, it must not prevent it
            log.warning("could not read final diff: %s", exc)
        try:
            final_sha = await workspaces.tree_sha("main")
        except Exception as exc:
            log.warning("could not read final tree sha: %s", exc)
    if final_sha is None:
        final_sha = derive_final_tree_sha(mission, events)
    report = build_report(
        mission,
        events,
        final_tree_sha=final_sha,
        diff_names=[f.path for f in parse_diff(diff_text)] if diff_text else None,
        diff_text=diff_text,
    )
    problems = consistency_check(report, mission)
    if problems:
        if not force:
            await asyncio.to_thread(
                _atomic_write,
                out_dir / "REPORT_REFUSED.txt",
                "Report refused:\n" + "\n".join(problems) + "\n",
            )
            raise ReportConsistencyError(problems)
        report = report.model_copy(update={"consistency_errors": problems})

    md = render_markdown(report)
    html = render_html(report, events)
    blob = json.dumps(
        {"report": report.model_dump(mode="json"), "mission": mission.model_dump(mode="json")}, indent=2
    )

    def _write_all() -> Path:
        _atomic_write(out_dir / "REPORT.md", md)
        _atomic_write(out_dir / "report.html", html)
        _atomic_write(out_dir / "mission.json", blob)
        if diff_text is not None:
            _atomic_write(out_dir / "final.diff", diff_text)
        refused = out_dir / "REPORT_REFUSED.txt"
        if refused.exists():
            refused.unlink()
        return out_dir / "REPORT.md"

    return await asyncio.to_thread(_write_all)


def make_report_writer(
    store: EventStore,
    workspaces: Workspaces | None,
    runs_dir: Path,
    *,
    force: bool = False,
) -> Callable[[Mission], Awaitable[None]]:
    """Orchestrator ``report_writer`` hook: writes into ``<runs_dir>/<mission_id>/``."""

    async def writer(mission: Mission) -> None:
        await write_report(mission, store, workspaces, out_dir=runs_dir / mission.id, force=force)

    return writer
