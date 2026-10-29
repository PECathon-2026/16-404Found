"""Service container shared by the FastAPI app and tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .db import Database
from .deps import Deps
from .events.bus import EventBus
from .graph.runner import MissionRunner
from .llm.router import LLMRouter
from .state.manager import StateManager
from .tools.base import ToolRegistry
from .tools.registry import build_registry


@dataclass
class Container:
    settings: Settings
    deps: Deps
    registry: ToolRegistry
    router: LLMRouter
    runner: MissionRunner


def build_container(settings: Settings, checkpointer: Any, db: Database | None = None) -> Container:
    settings.ensure_dirs()
    db = db or Database(settings.db_path)
    bus = EventBus(db)
    deps = Deps(settings=settings, db=db, bus=bus, state=StateManager(db, bus))
    router = LLMRouter(settings)
    deps.llm = router
    registry = build_registry()
    runner = MissionRunner(deps, registry, router, checkpointer)
    return Container(settings, deps, registry, router, runner)
