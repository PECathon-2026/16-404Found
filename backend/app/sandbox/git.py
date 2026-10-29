"""Trusted git helpers (invoked by tools/services, never by agents directly)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


def _lock_for(cwd: Path) -> asyncio.Lock:
    """One lock per (event loop, repository): parallel agents (tester || security) share a workspace and git's index
    is not safe for concurrent `git add`/`diff --cached`. Serialising per repo removes index.lock races."""
    key = (id(asyncio.get_running_loop()), os.path.realpath(cwd))
    lock = _LOCKS.get(key)
    if lock is None:
        lock = _LOCKS[key] = asyncio.Lock()
    return lock


class GitError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


async def git(cwd: Path, *args: str, env_extra: dict[str, str] | None = None, check: bool = True,
              timeout: float = 120.0, input_: bytes | None = None) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C.UTF-8"}
    env.update(env_extra or {})
    async with _lock_for(cwd):
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(cwd), env=env, stdin=asyncio.subprocess.PIPE if input_ is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(input_), timeout=timeout)
        except TimeoutError:
            proc.kill()
            raise GitError(f"git {args[0]} timed out") from None
    if check and proc.returncode != 0:
        raise GitError(err.decode("utf-8", "replace").strip() or f"git {args[0]} failed", proc.returncode or 1)
    return out.decode("utf-8", "replace")
