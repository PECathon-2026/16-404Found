"""Workspace manager: isolated copy of the repository + git baseline commit (ARCHITECTURE.md §C.3)."""
from __future__ import annotations

import fnmatch
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .git import git

EXCLUDE_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".next", ".mypy_cache",
                ".ruff_cache", "dist", "build", ".idea", ".vscode", ".tox"}
SECRET_PATTERNS = [".env", ".env.*", "*.pem", "id_rsa*", "id_ed25519*", "*.key", "*.p12", "*.pfx", "credentials.json", ".npmrc", ".pypirc"]
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 6000
MAX_TOTAL_BYTES = 250 * 1024 * 1024


@dataclass
class WorkspaceInfo:
    path: Path
    base_commit: str
    exclusions: list[dict[str, str]] = field(default_factory=list)


def _is_secret_name(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in SECRET_PATTERNS) and name != ".env.example"


async def prepare_workspace(src: Path, dest: Path) -> WorkspaceInfo:
    dest = Path(os.path.realpath(dest))
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    exclusions: list[dict[str, str]] = []
    src = src.resolve()
    n_files, total = 0, 0
    for root, dirs, files in os.walk(src, followlinks=False):
        rel_root = Path(root).relative_to(src)
        keep = []
        for d in dirs:
            if d in EXCLUDE_DIRS:
                exclusions.append({"path": str(rel_root / d), "reason": "excluded directory"})
            elif (Path(root) / d).is_symlink():
                exclusions.append({"path": str(rel_root / d), "reason": "symlink skipped"})
            else:
                keep.append(d)
        dirs[:] = keep
        (dest / rel_root).mkdir(parents=True, exist_ok=True)
        for f in files:
            p = Path(root) / f
            rel = rel_root / f
            if p.is_symlink():
                exclusions.append({"path": str(rel), "reason": "symlink skipped"})
            elif _is_secret_name(f):
                exclusions.append({"path": str(rel), "reason": "possible secret file excluded"})
            elif p.stat().st_size > MAX_FILE_BYTES:
                exclusions.append({"path": str(rel), "reason": "file larger than 5 MB"})
            else:
                n_files += 1
                total += p.stat().st_size
                if n_files > MAX_FILES or total > MAX_TOTAL_BYTES:
                    raise ValueError(f"repository too large for a mission workspace (>{MAX_FILES} files or >250 MB); import a smaller project")
                shutil.copy2(p, dest / rel)
    await git(dest, "init", "-q", "-b", "main")
    await git(dest, "config", "user.email", "devpilot@localhost")
    await git(dest, "config", "user.name", "DevPilot")
    await git(dest, "config", "commit.gpgsign", "false")
    (dest / ".git" / "info" / "exclude").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n.mypy_cache/\nnode_modules/\n.venv/\n")
    await git(dest, "add", "-A")
    await git(dest, "commit", "-q", "--allow-empty", "-m", "DevPilot baseline")
    base = (await git(dest, "rev-parse", "HEAD")).strip()
    return WorkspaceInfo(dest, base, exclusions)
