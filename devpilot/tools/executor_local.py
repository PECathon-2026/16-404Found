"""Local subprocess executor for DevPilot tools.

Implements `ports.Executor` using `asyncio.create_subprocess_exec` without shells,
running in a scrubbed environment with process-tree timeout management and output capping.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path

import psutil  # type: ignore[import-untyped]

from devpilot.core.ports import ExecResult

# Maximum output allowed in bytes (5 MB)
MAX_OUTPUT_BYTES = 5 * 1024 * 1024


def get_scrubbed_env(cwd: Path, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build a sanitized environment preventing credential and API key leakage.

    Only essential operating system variables are preserved. Secrets such as
    `ANTHROPIC_API_KEY`, AWS tokens, or GitHub tokens are strictly scrubbed.
    """
    safe_keys = {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "TERM",
    }

    env: dict[str, str] = {}
    for key in safe_keys:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val

    # Set PYTHONPATH to workspace directory so local imports resolve cleanly
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    # Merge explicit extra_env, filtering out any potential secret keys
    if extra_env:
        for k, v in extra_env.items():
            upper = k.upper()
            if any(term in upper for term in ("KEY", "SECRET", "TOKEN", "PASSW", "AUTH", "CRED")):
                continue
            env[k] = v

    return env


def kill_process_tree(pid: int) -> None:
    """Recursively kill a process and all its children across Windows and POSIX."""
    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                child.kill()
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            parent.kill()


class LocalExecutor:
    """Local process executor conforming to `ports.Executor`."""

    async def run(
        self,
        argv: list[str],
        cwd: Path,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run command argv directly without a shell, enforcing timeouts and output caps."""
        if not argv:
            raise ValueError("Command argv must not be empty")

        scrubbed_env = get_scrubbed_env(cwd, env)
        start_time = time.monotonic()
        timed_out = False

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=scrubbed_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=float(timeout_s)
                )
            except TimeoutError:
                timed_out = True
                if proc.pid:
                    kill_process_tree(proc.pid)
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=3.0
                    )
                except Exception:
                    stdout_bytes, stderr_bytes = b"", b""
                await proc.wait()

            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Cap output to MAX_OUTPUT_BYTES
            if len(stdout_bytes) > MAX_OUTPUT_BYTES:
                stdout_bytes = stdout_bytes[:MAX_OUTPUT_BYTES] + b"\n... [stdout capped at 5MB] ..."
            if len(stderr_bytes) > MAX_OUTPUT_BYTES:
                stderr_bytes = stderr_bytes[:MAX_OUTPUT_BYTES] + b"\n... [stderr capped at 5MB] ..."

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode if proc.returncode is not None else -1

            return ExecResult(
                argv=argv,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                duration_ms=duration_ms,
                timed_out=timed_out,
            )

        except FileNotFoundError as err:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return ExecResult(
                argv=argv,
                exit_code=127,
                stdout="",
                stderr=f"Executable not found: {argv[0]!r} ({err})",
                duration_ms=duration_ms,
                timed_out=False,
            )
