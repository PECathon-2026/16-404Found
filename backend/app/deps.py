from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .db import Database
from .events.bus import EventBus
from .state.manager import StateManager


@dataclass
class Deps:
    settings: Settings
    db: Database
    bus: EventBus
    state: StateManager
    llm: Any = None  # LLMRouter (set after construction to avoid import cycles)
    extra: dict[str, Any] = field(default_factory=dict)
