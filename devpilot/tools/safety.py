"""Safety layer: path validation, command allow/block lists, timeout enforcement."""

from __future__ import annotations

import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Command allow and block lists
# ---------------------------------------------------------------------------

ALLOWED_COMMANDS = {
    "pytest",
    "python",
    "python3",
    "python -m pytest",
    "python3 -m pytest",
    "ls",
    "cat",
    "git diff",
    "git status",
}

# These strings must NOT appear anywhere in a command
BLOCKED_PATTERNS = [
    r"\brm\b",
    r"\bsudo\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bssh\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bdd\b(?!\w)",          # dd as standalone word
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"[|][\s]*sh\b",          # pipe to sh
    r"[|][\s]*bash\b",        # pipe to bash
    r"\.env\b",               # accessing .env files
    r"\.git/(?!COMMIT_EDITMSG|HEAD|config$)",  # .git internals (allow diff/status)
    r"&&\s*(rm|sudo|curl|wget|ssh|chmod|chown|dd|mkfs|shutdown)",
]

_BLOCKED_RE = [re.compile(p) for p in BLOCKED_PATTERNS]

COMMAND_TIMEOUT = 30  # seconds
OUTPUT_SIZE_LIMIT = 50_000  # characters


class SafetyError(Exception):
    """Raised when a safety check fails."""


def check_path(path: str | Path, workspace_path: str | Path) -> Path:
    """
    Resolve path and ensure it is inside workspace_path.

    Raises SafetyError if the path is outside, contains '..', or is a symlink
    pointing outside the workspace.
    """
    workspace = Path(workspace_path).resolve()
    try:
        resolved = Path(path).resolve()
    except Exception as exc:
        raise SafetyError(f"Cannot resolve path: {path!r}: {exc}") from exc

    # Block '..' traversal attempts
    raw = str(path)
    if ".." in raw:
        raise SafetyError(f"Path traversal blocked: {path!r}")

    # Block absolute paths outside workspace
    if resolved.is_absolute() and not str(resolved).startswith(str(workspace)):
        raise SafetyError(
            f"Path outside workspace: {resolved!r} not under {workspace!r}"
        )

    # Block symlinks that escape workspace
    if resolved.is_symlink():
        real = Path(os.path.realpath(resolved))
        if not str(real).startswith(str(workspace)):
            raise SafetyError(f"Symlink escapes workspace: {resolved!r} -> {real!r}")

    return resolved


def check_command(command: str) -> None:
    """
    Validate that a command is on the allow list and contains no blocked patterns.

    Raises SafetyError if blocked.
    """
    cmd = command.strip()

    # Check blocked patterns first
    for pattern in _BLOCKED_RE:
        if pattern.search(cmd):
            raise SafetyError(f"Blocked command pattern matched: {cmd!r}")

    # Check allow list: command must start with an allowed prefix
    allowed = False
    for allowed_cmd in ALLOWED_COMMANDS:
        if cmd == allowed_cmd or cmd.startswith(allowed_cmd + " ") or cmd.startswith(allowed_cmd + "\t"):
            allowed = True
            break

    # Also allow python/python3 running a file that is within workspace
    if not allowed:
        if re.match(r"^python3?\s+\S+\.py", cmd):
            allowed = True

    if not allowed:
        raise SafetyError(f"Command not on allow list: {cmd!r}")


def is_command_blocked(command: str) -> bool:
    """Return True if the command would be blocked by the safety layer."""
    try:
        check_command(command)
        return False
    except SafetyError:
        return True


def truncate_output(output: str) -> str:
    """Truncate output that exceeds OUTPUT_SIZE_LIMIT."""
    if len(output) > OUTPUT_SIZE_LIMIT:
        return output[:OUTPUT_SIZE_LIMIT] + "\n... [output truncated]"
    return output
