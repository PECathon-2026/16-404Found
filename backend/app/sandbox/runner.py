"""Local-jail runner (fallback sandbox). Weaker than a container: it limits cwd, env, time, output and
file size, but a malicious repository's own test code can still read the host filesystem. The UI shows a
banner when this mode is active. (Docker runner: not implemented yet; see PROGRESS-TRACKER T2.04.)"""
from __future__ import annotations

import asyncio
import os
import resource
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 400_000


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    truncated: bool = False
    not_found: bool = False


def _limits(timeout_s: int):  # type: ignore[no-untyped-def]
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_s + 5, timeout_s + 10))
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
        except (ValueError, OSError):
            pass

    return apply


def sandbox_env(home: Path) -> dict[str, str]:
    py_bin = str(Path(sys.executable).parent)
    return {
        "PATH": f"{py_bin}:/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin",
        "HOME": str(home), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1", "CI": "1", "NO_COLOR": "1", "GIT_TERMINAL_PROMPT": "0",
    }


def _resolve_argv(argv: list[str]) -> list[str]:
    exe = os.path.basename(argv[0])
    if exe in {"python", "python3"}:
        return [sys.executable, *argv[1:]]
    if exe == "pytest":
        return [sys.executable, "-m", "pytest", *argv[1:]]
    return argv


def _kill(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class LocalJailRunner:
    mode = "local_jail"

    def __init__(self, scratch_home: Path):
        self.home = scratch_home
        self.home.mkdir(parents=True, exist_ok=True)

    async def run(self, argv: list[str], cwd: Path, timeout_s: int = 60, extra_env: dict[str, str] | None = None) -> ExecResult:
        start = time.monotonic()
        env = sandbox_env(self.home)
        env.update(extra_env or {})
        argv = _resolve_argv(argv)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True, preexec_fn=_limits(timeout_s),
            )
        except FileNotFoundError:
            return ExecResult(127, "", f"{argv[0]}: command not found", False, 0, not_found=True)
        timed_out = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            timed_out = True
            _kill(proc.pid)
            out, err = await proc.communicate()
        except BaseException:  # cancellation: never leave a process group running
            _kill(proc.pid)
            raise
        dur = int((time.monotonic() - start) * 1000)
        trunc = len(out) > MAX_OUTPUT or len(err) > MAX_OUTPUT
        return ExecResult(
            proc.returncode if proc.returncode is not None else -1,
            out[:MAX_OUTPUT].decode("utf-8", "replace"), err[:MAX_OUTPUT].decode("utf-8", "replace"),
            timed_out, dur, trunc,
        )
