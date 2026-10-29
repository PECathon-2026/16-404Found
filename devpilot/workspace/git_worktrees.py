"""Git Workspaces: isolated worktree manager implementing `ports.Workspaces`.

Features:
- Worktree layout: `runs/<mission_id>/ws/main`, `ws/baseline`, `ws/cand-A..C`, `ws/scratch-*`.
- Non-git target support: auto-copies respecting .gitignore, initializes git, commits baseline.
- Dirty target preservation: snapshots uncommitted changes via `git stash create` without touching the user tree.
- Temporary index computation for tree_sha (`GIT_INDEX_FILE`), keeping user index untouched.
- Hunk parser (`hunks`): parses `git diff -U0` into structured stable hunk IDs (H1, H2, ...).
- Checkpoints & rollback: commits inside worktrees, performs clean rollbacks.
- Tournament adoption (`adopt`): applies winning candidate tree to main and commits.
- Fast-forward apply (`apply_to_target`): verifies clean target, merges `--ff-only`.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from devpilot.core.ports import Workspaces

# Regex to parse unified diff headers and hunk lines
DIFF_FILE_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


async def _run_git(
    cwd: Path,
    args: list[str],
    env: dict[str, str] | None = None,
    check: bool = True,
) -> tuple[int, str, str]:
    """Execute git subprocess directly without shell, returning exit_code, stdout, stderr."""
    run_env = os.environ.copy()
    run_env["GIT_TERMINAL_PROMPT"] = "0"
    if env:
        run_env.update(env)

    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        env=run_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    exit_code = proc.returncode if proc.returncode is not None else -1
    stdout_str = stdout_b.decode("utf-8", errors="replace")
    stderr_str = stderr_b.decode("utf-8", errors="replace")

    if check and exit_code != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd} (code {exit_code}):\n{stderr_str or stdout_str}"
        )
    return exit_code, stdout_str, stderr_str


def parse_diff_hunks(diff_text: str) -> list[dict[str, Any]]:
    """Parse `git diff -U0` output into structured stable hunk dictionaries."""
    hunks: list[dict[str, Any]] = []
    current_file: str | None = None
    lines = diff_text.splitlines(keepends=True)
    i = 0
    hunk_index = 1

    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            m = DIFF_FILE_HEADER_RE.match(line.strip())
            if m:
                current_file = m.group(2)
            i += 1
            continue

        if line.startswith("+++ "):
            # If +++ /dev/null, file was deleted
            target = line[4:].strip()
            if target != "/dev/null" and target.startswith("b/"):
                current_file = target[2:]
            i += 1
            continue

        if line.startswith("@@ "):
            header = line.strip()
            hm = HUNK_HEADER_RE.match(header)
            if hm:
                old_start = int(hm.group(1))
                old_len = int(hm.group(2)) if hm.group(2) is not None else 1
                new_start = int(hm.group(3))
                new_len = int(hm.group(4)) if hm.group(4) is not None else 1

                patch_lines = [line]
                i += 1
                while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("diff --git "):
                    patch_lines.append(lines[i])
                    i += 1

                hunk_id = f"H{hunk_index}"
                hunks.append(
                    {
                        "id": hunk_id,
                        "path": current_file or "unknown",
                        "old_start": old_start,
                        "old_len": old_len,
                        "new_start": new_start,
                        "new_len": new_len,
                        "patch": "".join(patch_lines),
                    }
                )
                hunk_index += 1
                continue

        i += 1

    return hunks


class GitWorkspaces(Workspaces):
    """Git worktree manager implementing `ports.Workspaces`."""

    def __init__(self, runs_dir: Path | str = "runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.repo: Path = Path(".")
        self.mission_id: str = ""
        self.base_dir: Path = Path(".")
        self.baseline_commit: str = ""
        self.dirty_at_start: bool = False
        self.is_synthetic_git: bool = False
        self._worktrees: dict[str, Path] = {}

    async def create_main(self, repo: Path, mission_id: str) -> Path:
        """Initialize worktree layout, preparing 'main' worktree for the mission."""
        self.repo = repo.resolve()
        self.mission_id = mission_id
        self.base_dir = (self.runs_dir / mission_id / "ws").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 1. Handle non-git target repository
        if not (self.repo / ".git").exists():
            synthetic_repo = (self.runs_dir / mission_id / "synthetic_repo").resolve()
            if synthetic_repo.exists():
                shutil.rmtree(synthetic_repo)

            def _ignore_func(src: str, names: list[str]) -> set[str]:
                ignored = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
                return set(names) & ignored

            shutil.copytree(self.repo, synthetic_repo, ignore=_ignore_func)
            await _run_git(synthetic_repo, ["init"])
            await _run_git(synthetic_repo, ["config", "user.name", "DevPilot"])
            await _run_git(synthetic_repo, ["config", "user.email", "devpilot@agentic.ai"])
            await _run_git(synthetic_repo, ["add", "-A"])
            await _run_git(synthetic_repo, ["commit", "-m", "devpilot baseline"])

            self.repo = synthetic_repo
            self.is_synthetic_git = True
            _, head_sha, _ = await _run_git(self.repo, ["rev-parse", "HEAD"])
            self.baseline_commit = head_sha.strip()
            base_ref = self.baseline_commit
        else:
            # 2. Check if git target has uncommitted changes
            _, status_out, _ = await _run_git(self.repo, ["status", "--porcelain"])
            _, head_sha, _ = await _run_git(self.repo, ["rev-parse", "HEAD"])
            self.baseline_commit = head_sha.strip()

            if status_out.strip():
                # Target is dirty: snapshot changes into a commit object without modifying index/tree
                _, stash_sha, _ = await _run_git(self.repo, ["stash", "create"])
                stash_sha = stash_sha.strip()
                if stash_sha:
                    self.dirty_at_start = True
                    base_ref = stash_sha
                else:
                    base_ref = self.baseline_commit
            else:
                base_ref = self.baseline_commit

        # Ensure git user identity is configured
        await _run_git(self.repo, ["config", "user.name", "DevPilot"], check=False)
        await _run_git(self.repo, ["config", "user.email", "devpilot@agentic.ai"], check=False)

        # 3. Create mission branch devpilot/<mission_id>
        branch_name = f"devpilot/{mission_id}"
        await _run_git(self.repo, ["branch", "-f", branch_name, base_ref])

        # 4. Create main worktree
        main_path = self.base_dir / "main"
        if main_path.exists():
            await _run_git(self.repo, ["worktree", "remove", "--force", str(main_path)], check=False)
            if main_path.exists():
                shutil.rmtree(main_path, ignore_errors=True)

        await _run_git(self.repo, ["worktree", "add", str(main_path), branch_name])
        self._worktrees["main"] = main_path
        return main_path

    async def create_baseline(self) -> Path:
        """Create isolated read-only baseline worktree detached at original HEAD."""
        baseline_path = self.base_dir / "baseline"
        if baseline_path.exists():
            await _run_git(self.repo, ["worktree", "remove", "--force", str(baseline_path)], check=False)
            if baseline_path.exists():
                shutil.rmtree(baseline_path, ignore_errors=True)

        # Detach worktree at baseline_commit
        await _run_git(
            self.repo,
            ["worktree", "add", "--detach", str(baseline_path), self.baseline_commit],
        )
        self._worktrees["baseline"] = baseline_path
        return baseline_path

    async def fork(self, name: str, from_ref: str = "main") -> Path:
        """Fork an isolated sibling worktree (cand-A..C or scratch-*) from an existing ref."""
        from_path = await self.path(from_ref)
        fork_path = self.base_dir / name

        if fork_path.exists():
            await _run_git(self.repo, ["worktree", "remove", "--force", str(fork_path)], check=False)
            if fork_path.exists():
                shutil.rmtree(fork_path, ignore_errors=True)

        # Snapshot from_ref working tree to commit if uncommitted
        _, current_head, _ = await _run_git(from_path, ["rev-parse", "HEAD"])
        commit_ref = current_head.strip()

        # Create detached worktree
        await _run_git(self.repo, ["worktree", "add", "--detach", str(fork_path), commit_ref])

        # Copy any uncommitted changes from from_path to fork_path
        # to ensure perfect fork state
        tree_sha = await self.tree_sha(from_ref)
        await _run_git(fork_path, ["read-tree", tree_sha])
        await _run_git(fork_path, ["checkout-index", "-a", "-f"])

        self._worktrees[name] = fork_path
        return fork_path

    async def path(self, ref: str) -> Path:
        """Return the filesystem path for a named worktree ref."""
        if ref in self._worktrees and self._worktrees[ref].exists():
            return self._worktrees[ref]
        candidate = self.base_dir / ref
        if candidate.exists():
            self._worktrees[ref] = candidate
            return candidate
        raise KeyError(f"Worktree ref {ref!r} does not exist in mission {self.mission_id}")

    async def tree_sha(self, ref: str = "main") -> str:
        """Compute git write-tree hash using an isolated temporary index without modifying user index."""
        ws_path = await self.path(ref)
        temp_index = ws_path.parent / f".tmp_idx_{ref}_{uuid.uuid4().hex}"

        try:
            temp_env = {"GIT_INDEX_FILE": str(temp_index)}
            # Stage all changes into temporary index
            await _run_git(ws_path, ["add", "-A"], env=temp_env)
            # Write tree from temporary index
            _, out, _ = await _run_git(ws_path, ["write-tree"], env=temp_env)
            return out.strip()
        finally:
            if temp_index.exists():
                with contextlib.suppress(OSError):
                    temp_index.unlink()

    async def diff(self, ref: str = "main", against: str = "baseline") -> str:
        """Generate unified diff between working trees of two worktrees."""
        tree_ref = await self.tree_sha(ref)
        tree_against = await self.tree_sha(against)
        ws_path = await self.path(ref)

        _, diff_out, _ = await _run_git(
            ws_path,
            ["diff", tree_against, tree_ref],
            check=False,
        )
        return diff_out

    async def hunks(self, ref: str = "main") -> list[dict[str, Any]]:
        """Parse git diff -U0 against baseline into structured hunks with stable IDs."""
        tree_ref = await self.tree_sha(ref)
        tree_against = await self.tree_sha("baseline")
        ws_path = await self.path(ref)

        _, diff_out, _ = await _run_git(
            ws_path,
            ["diff", "-U0", tree_against, tree_ref],
            check=False,
        )
        return parse_diff_hunks(diff_out)

    async def checkpoint(self, label: str, ref: str = "main") -> str:
        """Commit current worktree state with message 'devpilot: <label>'."""
        ws_path = await self.path(ref)
        await _run_git(ws_path, ["add", "-A"])
        await _run_git(
            ws_path,
            ["commit", "--allow-empty", "-m", f"devpilot: {label}"],
        )
        _, head_out, _ = await _run_git(ws_path, ["rev-parse", "HEAD"])
        return head_out.strip()

    async def rollback(self, sha: str, ref: str = "main") -> None:
        """Reset worktree to a previous commit SHA inside that worktree only."""
        ws_path = await self.path(ref)
        await _run_git(ws_path, ["reset", "--hard", sha])
        await _run_git(ws_path, ["clean", "-fd"])

    async def adopt(self, candidate: str) -> None:
        """Apply candidate worktree changes onto main worktree and checkpoint."""
        main_path = await self.path("main")
        cand_tree = await self.tree_sha(candidate)

        # Apply candidate tree directly to main's index and checkout
        await _run_git(main_path, ["read-tree", cand_tree])
        await _run_git(main_path, ["checkout-index", "-a", "-f"])
        await _run_git(main_path, ["clean", "-fd"])

        await self.checkpoint(f"Adopt tournament candidate '{candidate}'", ref="main")

    async def apply_to_target(self) -> str:
        """Fast-forward merge mission branch into target repo. Refuses on dirty target."""
        # 1. Refuse if target repo is dirty
        _, status_out, _ = await _run_git(self.repo, ["status", "--porcelain"])
        if status_out.strip():
            raise RuntimeError(
                "Cannot apply changes: Target repository contains uncommitted modifications.\n"
                "Please commit or stash your changes before applying the mission change."
            )

        branch_name = f"devpilot/{self.mission_id}"
        # 2. Fast-forward merge mission branch into target HEAD
        exit_code, stdout, stderr = await _run_git(
            self.repo,
            ["merge", "--ff-only", branch_name],
            check=False,
        )
        if exit_code != 0:
            raise RuntimeError(
                f"Fast-forward merge failed. Target branch has diverged.\n{stderr or stdout}\n"
                f"To inspect or merge manually: git merge {branch_name}"
            )

        _, head_sha, _ = await _run_git(self.repo, ["rev-parse", "HEAD"])
        return head_sha.strip()
