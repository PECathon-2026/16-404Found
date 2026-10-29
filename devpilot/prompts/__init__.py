"""Prompt library: the shared constitution and one instruction file per cognitive mode.

The prompt compiler places the constitution first and the mode prompt second, both as cache
breakpoints, so the text is loaded verbatim and cached here. Both are plain markdown files
beside this module; hatch ships them with the wheel because they live inside the package.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

PROMPTS_DIR: Path = Path(__file__).resolve().parent
MODES_DIR: Path = PROMPTS_DIR / "modes"


@cache
def load_constitution() -> str:
    """Return the shared system prompt used by every agent."""
    return (PROMPTS_DIR / "constitution.md").read_text(encoding="utf-8")


@cache
def load_mode_prompt(mode_id: str) -> str:
    """Return the instruction text for ``mode_id``; ``KeyError`` if there is no such mode prompt."""
    # Reject anything that is not a plain mode id so a caller cannot read arbitrary files.
    path = MODES_DIR / f"{mode_id}.md"
    if not mode_id or "/" in mode_id or "\\" in mode_id or not path.is_file():
        raise KeyError(f"unknown mode id {mode_id!r}")
    return path.read_text(encoding="utf-8")
