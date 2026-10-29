"""Git tools: git_diff between original and workspace, git_status."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def git_diff(original_path: str, workspace_path: str) -> str:
    """
    Compute a unified diff between original_path and workspace_path.

    Uses git diff --no-index for repos not sharing a git history.
    Returns the diff as a string (empty string if no changes).
    """
    orig = Path(original_path).resolve()
    ws = Path(workspace_path).resolve()

    try:
        proc = subprocess.run(
            ["git", "diff", "--no-index", str(orig), str(ws)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # git diff --no-index exits 1 when there are differences, 0 when same
        return proc.stdout
    except subprocess.TimeoutExpired:
        return "ERROR: git diff timed out"
    except FileNotFoundError:
        return "ERROR: git not found"


def git_status(workspace_path: str) -> str:
    """Return git status output for the workspace (if it is a git repo)."""
    ws = Path(workspace_path).resolve()
    try:
        proc = subprocess.run(
            ["git", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(ws),
        )
        return proc.stdout or proc.stderr
    except Exception as exc:
        return f"ERROR: {exc}"


def git_diff_workspace(workspace_path: str) -> str:
    """Return the diff of uncommitted changes within workspace_path."""
    ws = Path(workspace_path).resolve()
    try:
        proc = subprocess.run(
            ["git", "diff"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(ws),
        )
        return proc.stdout
    except Exception as exc:
        return f"ERROR: {exc}"
