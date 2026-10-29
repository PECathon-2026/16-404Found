"""Unit tests for the LocalExecutor process manager."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from devpilot.tools.executor_local import LocalExecutor, get_scrubbed_env


@pytest.mark.asyncio
async def test_executor_successful_run(tmp_path: Path) -> None:
    """Subprocess executes successfully and captures stdout."""
    executor = LocalExecutor()
    res = await executor.run(
        [sys.executable, "-c", "print('hello devpilot')"],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.exit_code == 0
    assert "hello devpilot" in res.stdout
    assert res.timed_out is False
    assert res.duration_ms >= 0


@pytest.mark.asyncio
async def test_executor_nonzero_exit_and_stderr(tmp_path: Path) -> None:
    """Nonzero exit code and stderr are captured properly."""
    executor = LocalExecutor()
    res = await executor.run(
        [sys.executable, "-c", "import sys; sys.stderr.write('error msg'); sys.exit(42)"],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.exit_code == 42
    assert "error msg" in res.stderr
    assert res.timed_out is False


@pytest.mark.asyncio
async def test_executor_scrubbed_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Subprocess does not inherit sensitive API keys or secret environment variables."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret-token")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "super-secret-aws-token")

    env = get_scrubbed_env(tmp_path)
    assert "ANTHROPIC_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env

    executor = LocalExecutor()
    code = (
        "import os\n"
        "assert 'ANTHROPIC_API_KEY' not in os.environ\n"
        "assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
        "print('clean')\n"
    )
    res = await executor.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.exit_code == 0
    assert "clean" in res.stdout


@pytest.mark.asyncio
async def test_executor_timeout_kills_process(tmp_path: Path) -> None:
    """Process exceeding timeout is killed and timed_out flag is True."""
    executor = LocalExecutor()
    res = await executor.run(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        cwd=tmp_path,
        timeout_s=1,
    )
    assert res.timed_out is True
    assert res.exit_code != 0


@pytest.mark.asyncio
async def test_executor_nonexistent_binary(tmp_path: Path) -> None:
    """Nonexistent binary returns exit code 127 without raising unhandled exception."""
    executor = LocalExecutor()
    res = await executor.run(
        ["non_existent_command_12345"],
        cwd=tmp_path,
        timeout_s=5,
    )
    assert res.exit_code == 127
    assert "Executable not found" in res.stderr
