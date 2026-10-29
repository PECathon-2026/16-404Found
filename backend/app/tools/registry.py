from __future__ import annotations

from . import impl_exec, impl_fs, impl_mission, impl_sec
from .base import ToolRegistry


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for mod in (impl_fs, impl_exec, impl_sec, impl_mission):
        for spec in mod.SPECS:
            reg.register(spec)
    return reg
