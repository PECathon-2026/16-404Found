"""The mission orchestrator: a deterministic state machine that chooses which cognitive mode runs next.

Pure, unit-tested modules: ``transitions``, ``ac_rules``, ``progress``, ``guards``, ``dossier``,
``scheduler``. The effectful driver is ``orchestrator.Orchestrator``.
"""

from __future__ import annotations

from devpilot.orchestrator.orchestrator import Orchestrator

__all__ = ["Orchestrator"]
