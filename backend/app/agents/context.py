from __future__ import annotations

from pathlib import Path
from typing import Any

from ..deps import Deps
from ..sandbox.runner import LocalJailRunner
from ..tools.base import ToolContext


def make_ctx(deps: Deps, mission: dict[str, Any], agent_id: str, task: dict[str, Any] | None = None, exe_id: str | None = None) -> ToolContext:
    home = deps.settings.artifacts_dir / mission["id"] / "home"
    return ToolContext(
        deps=deps, mission_id=mission["id"], agent_id=agent_id, workspace=Path(mission["workspace_path"]), runner=LocalJailRunner(home),
        task_id=task["id"] if task else None, task_kind=task["kind"] if task else None, execution_id=exe_id,
        config=mission["config"] or {}, base_commit=mission["base_commit"] or "",
    )
