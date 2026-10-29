"""Command tool: run shell commands through the safety layer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.safety import (
    SafetyError,
    check_command,
    check_path,
    COMMAND_TIMEOUT,
    truncate_output,
)


def run_command(
    command: str,
    workspace_path: str,
    cwd: str | None = None,
    simulate_missing: str | None = None,
) -> dict:
    """
    Run a shell command inside workspace_path, enforcing the safety layer.

    Returns dict with keys: command, exit_code, stdout, stderr, blocked, error.
    simulate_missing: if set, pretend this tool/command is not found.
    """
    result: dict = {
        "command": command,
        "exit_code": -1,
        "stdout": "",
        "stderr": "",
        "blocked": False,
        "error": None,
    }

    # Safety check
    try:
        check_command(command)
    except SafetyError as exc:
        result["blocked"] = True
        result["error"] = str(exc)
        result["exit_code"] = 126  # command not executable (conventional)
        return result

    # Simulate missing tool
    if simulate_missing:
        cmd_lower = command.strip().split()[0].lower()
        if simulate_missing.lower() in cmd_lower or simulate_missing.lower() in command:
            result["exit_code"] = 127
            result["stderr"] = f"bash: {simulate_missing}: command not found"
            result["error"] = f"Simulated missing: {simulate_missing}"
            return result

    # Determine working directory
    if cwd:
        run_cwd = str(check_path(cwd, workspace_path))
    else:
        run_cwd = str(Path(workspace_path).resolve())

    # Pick python executable
    python_exe = sys.executable

    # Replace bare 'python' with the real executable path
    cmd_parts = command.strip()
    if cmd_parts.startswith("python3 ") or cmd_parts == "python3":
        cmd_parts = python_exe + cmd_parts[7:]
    elif cmd_parts.startswith("python ") or cmd_parts == "python":
        cmd_parts = python_exe + cmd_parts[6:]

    try:
        proc = subprocess.run(
            cmd_parts,
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            cwd=run_cwd,
        )
        result["exit_code"] = proc.returncode
        result["stdout"] = truncate_output(proc.stdout)
        result["stderr"] = truncate_output(proc.stderr)
    except subprocess.TimeoutExpired:
        result["exit_code"] = 124
        result["error"] = f"Command timed out after {COMMAND_TIMEOUT}s"
    except Exception as exc:
        result["exit_code"] = 1
        result["error"] = str(exc)

    return result
