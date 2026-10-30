# ruff: noqa: E402
from __future__ import annotations

import os

# Hermetic tests: never read real provider keys from the shell or backend/.env (env vars take precedence over .env).
for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "GITHUB_TOKEN"):
    os.environ[_k] = ""  # noqa: E402

import textwrap
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.deps import Deps
from app.events.bus import EventBus
from app.sandbox.runner import LocalJailRunner
from app.sandbox.workspace import prepare_workspace
from app.state.manager import StateManager
from app.tools.base import ToolContext
from app.tools.registry import build_registry

CALC = textwrap.dedent('''
    def add(a, b):
        return a + b


    def divide(a, b):
        if b == 0:
            raise ValueError("division by zero")
        return a / b
''')
TEST_CALC = textwrap.dedent('''
    import pytest
    from calc import add, divide


    def test_add():
        assert add(1, 2) == 3


    def test_divide():
        assert divide(6, 3) == 2


    def test_divide_zero():
        with pytest.raises(ValueError):
            divide(1, 0)
''')


def write_repo(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(DEVPILOT_DATA_DIR=str(tmp_path / "data"))
    s.ensure_dirs()
    return s


@pytest.fixture
def deps(settings: Settings) -> Deps:
    db = Database(":memory:")
    bus = EventBus(db)
    return Deps(settings=settings, db=db, bus=bus, state=StateManager(db, bus))


@pytest.fixture
def registry():
    return build_registry()


@pytest.fixture
async def make_ctx(deps: Deps, tmp_path: Path):
    counter = {"n": 0}

    async def _make(files: dict[str, str], agent: str = "developer", task_kind: str | None = "IMPLEMENT", config: dict | None = None) -> ToolContext:
        counter["n"] += 1
        src = write_repo(tmp_path / f"src{counter['n']}", files)
        ws = await prepare_workspace(src, tmp_path / f"ws{counter['n']}")
        m = deps.state.create_mission("rep_x", "t", "req", config or {}, "scripted")
        deps.state.update_mission(m["id"], workspace_path=str(ws.path), base_commit=ws.base_commit)
        return ToolContext(deps=deps, mission_id=m["id"], agent_id=agent, workspace=ws.path, runner=LocalJailRunner(tmp_path / "home"),
                           task_kind=task_kind, config=config or {}, base_commit=ws.base_commit)
    return _make


@pytest.fixture
def calc_files() -> dict[str, str]:
    return {"calc.py": CALC, "tests/test_calc.py": TEST_CALC}
