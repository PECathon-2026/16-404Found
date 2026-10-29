"""Command allowlisting (G3). Default-deny; deny rules are evaluated before allow rules."""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from .pathjail import PathViolation, resolve_in

METACHARS = [";", "|", "&", ">", "<", "`", "$(", "${", "\n", "\r"]

ALWAYS_DENIED_EXECS = {
    "rm", "rmdir", "sudo", "su", "chmod", "chown", "chgrp", "mount", "umount", "dd", "mkfs", "kill", "killall", "pkill",
    "shutdown", "reboot", "halt", "curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "sftp", "ftp", "telnet", "docker",
    "kubectl", "sh", "bash", "zsh", "fish", "csh", "env", "printenv", "eval", "exec", "source", "mv", "cp", "ln", "touch",
    "tee", "xargs", "find", "awk", "sed", "perl", "ruby", "php", "osascript", "open", "launchctl", "systemctl", "crontab",
    "brew", "apt", "apt-get", "yum", "dnf", "pip", "pip3", "npx", "yarn", "pnpm", "go", "cargo", "make",
}

READ_ONLY = {"ls", "cat", "head", "tail", "wc", "pwd", "grep", "rg", "echo"}
GIT_READ = {"status", "log", "diff", "show", "ls-files", "rev-parse", "branch", "blame"}
GIT_FORBIDDEN_FLAGS = {"-c", "-C", "--git-dir", "--work-tree", "--exec-path", "--upload-pack", "--receive-pack", "--output"}
PY_MODULES = {
    "discovery": {"pytest", "unittest", "pip"},
    "dev": {"pytest", "unittest", "ruff", "black", "mypy", "compileall", "pip"},
    "test": {"pytest", "unittest"},
    "verify": {"pytest", "unittest", "compileall"},
}
NPM_SCRIPTS = {"test", "lint", "build", "typecheck"}
PIP_READ = {"list", "show", "freeze"}


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    argv: list[str] | None = None


def parse_command(command: str | list[str]) -> tuple[list[str] | None, str]:
    """Return (argv, error). Strings are shlex-split; shell metacharacters are rejected outright."""
    if isinstance(command, list):
        if not command or not all(isinstance(a, str) for a in command):
            return None, "command must be a non-empty list of strings"
        return command, ""
    for m in METACHARS:
        if m in command:
            return None, f"shell metacharacter {m!r} is not allowed (commands run without a shell)"
    try:
        return shlex.split(command), ""
    except ValueError as e:
        return None, f"unparseable command: {e}"


def _looks_like_path(a: str) -> bool:
    return "/" in a or a.startswith(".") or a.startswith("~") or a == ".."


def _check_paths(argv: list[str], ws: Path) -> str:
    for a in argv[1:]:
        if a.startswith("-") and "=" in a:
            a = a.split("=", 1)[1]
        if a.startswith("-") or not _looks_like_path(a):
            continue
        base = a.split("::", 1)[0]  # pytest node ids
        try:
            resolve_in(ws, base)
        except PathViolation as e:
            return f"path argument {a!r} rejected: {e}"
    return ""


def check_command(command: str | list[str], profile: str, workspace: Path, *, allow_install_deps: bool = False,
                  extra_allowed: tuple[str, ...] = ()) -> PolicyDecision:
    argv, err = parse_command(command)
    if argv is None:
        return PolicyDecision(False, err)
    exe = os.path.basename(argv[0])
    if exe in ALWAYS_DENIED_EXECS and exe not in extra_allowed:
        return PolicyDecision(False, f"executable {exe!r} is always denied")
    if "/" in argv[0] and exe not in {"python", "python3"}:
        return PolicyDecision(False, "executables must be referenced by bare name")
    if profile not in PY_MODULES:
        return PolicyDecision(False, f"unknown profile {profile!r}")
    perr = _check_paths(argv, workspace)
    if perr:
        return PolicyDecision(False, perr)

    if exe in READ_ONLY:
        if profile == "test":
            return PolicyDecision(False, f"{exe} is not allowed in the {profile} profile")
        return PolicyDecision(True, argv=argv)

    if exe == "git":
        sub = next((a for a in argv[1:] if not a.startswith("-")), None)
        flags = {a.split("=")[0] for a in argv[1:] if a.startswith("-")}
        if flags & GIT_FORBIDDEN_FLAGS:
            return PolicyDecision(False, "git flag not allowed")
        if sub not in GIT_READ:
            return PolicyDecision(False, f"git {sub or ''} is not allowed (read-only subcommands only)".strip())
        if sub == "branch" and any(not a.startswith("-") for a in argv[argv.index("branch") + 1:]):
            return PolicyDecision(False, "git branch with arguments is not allowed")
        return PolicyDecision(True, argv=argv)

    if exe in {"python", "python3"}:
        rest = argv[1:]
        if rest == ["--version"] or rest == ["-V"]:
            return PolicyDecision(True, argv=argv)
        if len(rest) >= 2 and rest[0] == "-m":
            mod = rest[1]
            if mod not in PY_MODULES[profile]:
                return PolicyDecision(False, f"python -m {mod} is not allowed in the {profile} profile")
            if mod == "pip":
                if len(rest) >= 3 and rest[2] in PIP_READ:
                    return PolicyDecision(True, argv=argv)
                if len(rest) >= 3 and rest[2] == "install" and allow_install_deps:
                    return PolicyDecision(True, argv=argv)
                return PolicyDecision(False, "pip install requires permissions.allow_install_deps")
            return PolicyDecision(True, argv=argv)
        return PolicyDecision(False, "python is only allowed as `python -m <module>` or `--version` (no -c, no scripts)")

    if exe in {"pytest", "ruff", "black", "mypy"}:
        if exe == "pytest" and profile in PY_MODULES:
            return PolicyDecision(True, argv=argv)
        if exe in {"ruff", "black", "mypy"} and profile == "dev":
            return PolicyDecision(True, argv=argv)
        return PolicyDecision(False, f"{exe} is not allowed in the {profile} profile")

    if exe == "node":
        if argv[1:] in (["--version"], ["-v"]):
            return PolicyDecision(True, argv=argv)
        return PolicyDecision(False, "node is only allowed with --version")

    if exe == "npm":
        rest = argv[1:]
        if profile in {"dev", "test", "verify"}:
            if rest[:1] == ["test"]:
                return PolicyDecision(True, argv=argv)
            if rest[:2] and rest[0] == "run" and len(rest) >= 2 and rest[1] in NPM_SCRIPTS and profile == "dev":
                return PolicyDecision(True, argv=argv)
        return PolicyDecision(False, "npm is only allowed for test/run lint|build|typecheck (no install)")

    if exe in extra_allowed:
        return PolicyDecision(True, argv=argv)
    return PolicyDecision(False, f"executable {exe!r} is not on the {profile} allowlist")
