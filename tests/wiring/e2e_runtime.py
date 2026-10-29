"""Scripted AgentRuntime for wiring/CLI end-to-end tests (imported as ``e2e_runtime``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orch_helpers import (
    ScriptedRuntime,
    approve_review,
    make_brief,
    make_plan,
    make_report,
    make_spec,
    make_suite,
    pass_security,
    pass_verdict,
)

from devpilot.core import models as m
from devpilot.core.ports import ModeInvocation


def scripted_runtime(bb: Any) -> ScriptedRuntime:
    """Scripts a clean one-task mission; the Samurai step edits the *real* main worktree."""
    rt = ScriptedRuntime(bb)
    main = Path(bb.mission.workspace_path)

    def implement(_: ModeInvocation) -> m.ChangeReport:
        target = main / "pager" / "paginate.py"
        target.write_text(
            target.read_text(encoding="utf-8") + "\n# fixed by the scripted samurai\n", encoding="utf-8"
        )
        return make_report()

    rt.script("scout.recon", make_brief())
    rt.script("shogun.analyze", make_spec())
    rt.script("shogun.plan", make_plan(("T1", ["pager/paginate.py"], [])))
    rt.script("shogun.premortem", m.PreMortem(risks=[]))
    rt.script("sentinel.author_acceptance", make_suite())
    rt.script("shogun.reflect", m.Reflection(what_worked=[], what_failed=[], lessons=[]))
    rt.script("reviewer.review", approve_review)
    rt.script("security.inspect", pass_security)
    rt.script("samurai.implement", implement)
    rt.script("verifier.verify", pass_verdict())
    return rt
