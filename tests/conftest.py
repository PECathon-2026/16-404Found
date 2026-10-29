"""Root test configuration.

* Skips fsync in the event store so the suite is fast (durability is tested explicitly elsewhere).
* Provides ``git_repo`` (a temp repository holding a copy of fixtures/fx2_bug_pagination) and makes the
  orchestrator test fakes importable as ``orch_helpers`` from any test directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DEVPILOT_FSYNC", "0")

ROOT = Path(__file__).resolve().parents[1]
for _d in ("orchestrator", "wiring"):
    sys.path.insert(0, str(ROOT / "tests" / _d))

FIXTURE = ROOT / "fixtures" / "fx2_bug_pagination"


def run_vcs(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A fresh repository containing a copy of fixtures/fx2_bug_pagination."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    run_vcs(repo, "init", "-q", "-b", "main")
    run_vcs(repo, "add", "-A")
    run_vcs(repo, "commit", "-q", "-m", "initial")
    return repo
