"""File tools: read_file, search_code, edit_file, list_files."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Optional

from tools.safety import check_path, SafetyError


def read_file(path: str, workspace_path: str) -> str:
    """
    Read and return the content of a file inside workspace_path.

    Raises SafetyError if path is outside the workspace.
    """
    resolved = check_path(path, workspace_path)
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")
    if not resolved.is_file():
        raise IsADirectoryError(f"Path is a directory: {resolved}")
    return resolved.read_text(encoding="utf-8")


def edit_file(path: str, content: str, workspace_path: str) -> None:
    """
    Write content to a file inside workspace_path, creating parent dirs as needed.

    Raises SafetyError if path is outside the workspace.
    """
    resolved = check_path(path, workspace_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")


def search_code(
    pattern: str,
    workspace_path: str,
    file_glob: str = "*.py",
) -> list[dict]:
    """
    Search for a text pattern in files matching file_glob within workspace_path.

    Returns list of {file, line, content} dicts.
    """
    workspace = Path(workspace_path).resolve()
    results = []
    for root, _dirs, files in os.walk(workspace):
        for fname in files:
            if fnmatch.fnmatch(fname, file_glob):
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if pattern.lower() in line.lower():
                            results.append(
                                {
                                    "file": str(fpath.relative_to(workspace)),
                                    "line": i,
                                    "content": line.rstrip(),
                                }
                            )
                except Exception:
                    continue
    return results


def list_files(workspace_path: str, file_glob: str = "*") -> list[str]:
    """
    List all files within workspace_path matching file_glob.

    Returns paths relative to workspace_path.
    """
    workspace = Path(workspace_path).resolve()
    results = []
    for root, _dirs, files in os.walk(workspace):
        for fname in files:
            if fnmatch.fnmatch(fname, file_glob):
                fpath = Path(root) / fname
                results.append(str(fpath.relative_to(workspace)))
    return sorted(results)
