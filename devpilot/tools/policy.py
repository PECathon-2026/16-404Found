"""Security policy enforcement for filesystem access, command execution, and test integrity.

Provides:
- Filesystem path jail with symlink, traversal, and UNC/drive letter containment checks.
- Default-deny command classification across allow / ask / deny tiers with metacharacter rejection.
- AST-level test protection that prevents removing/altering existing assertions or adding skip/xfail markers.
- Secret redaction for tool outputs and sensitive configuration files.
"""

from __future__ import annotations

import ast
import contextlib
import fnmatch
import re
from pathlib import Path, PurePath
from typing import Literal

# Shell metacharacters forbidden in command arguments
METACHARACTER_RE = re.compile(r"[;&|`$<>\r\n]")

# Secret extraction regex patterns for output redaction (docs/07 §3)
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9]{32,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PRIVATE) KEY-----[\s\S]*?-----END (?:RSA|EC|OPENSSH|PRIVATE) KEY-----"),
    "generic_assign": re.compile(r"(?i)(api[_-]?key|secret|passw(?:or)?d|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    "conn_string": re.compile(r"(?i)(?:postgres|mysql|mongodb)://[^:\s]+:[^@\s]+@"),
}

DEFAULT_WRITE_DENY = [
    ".git/**",
    ".github/workflows/**",
    "**/.env*",
    "**/*.pem",
    "**/id_rsa*",
    "poetry.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
]

DEFAULT_READ_REDACT = [
    "**/.env*",
    "**/*secret*",
    "**/*.pem",
    "**/id_rsa*",
]

DEFAULT_ALLOW_PATTERNS = [
    "python -m pytest *",
    "pytest *",
    "python -m unittest *",
    "python -m ruff check *",
    "ruff check *",
    "python -m flake8 *",
    "python -m mypy *",
    "python -m bandit *",
    "semgrep --config auto *",
    "npm test",
    "npm run test *",
    "npm run lint *",
    "npx jest *",
    "git status *",
    "git diff *",
    "git log *",
    "git show *",
    "python -c *",
]

DEFAULT_ASK_PATTERNS = [
    "pip install *",
    "python -m pip install *",
    "npm install *",
    "npm ci",
]

DEFAULT_DENY_PATTERNS = [
    "rm *",
    "rmdir *",
    "del *",
    "Remove-Item *",
    "format *",
    "mkfs*",
    "dd *",
    "git push *",
    "git reset --hard*",
    "git clean *",
    "git checkout -- *",
    "git rebase *",
    "git commit *",
    "curl *",
    "wget *",
    "Invoke-WebRequest *",
    "ssh *",
    "scp *",
    "sudo *",
    "chmod *",
    "chown *",
    "shutdown *",
    "reboot *",
    "powershell *",
    "cmd *",
    "bash *",
    "sh *",
]


class PolicyDenied(Exception):
    """Raised when an operation is blocked by security policy."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def resolve_in_workspace(ws: Path, rel: str) -> Path:
    """Resolve a relative or absolute path strictly within the workspace directory.

    Resolves symlinks, `..`, Windows drive letters, and UNC shares.
    Raises PolicyDenied if the resolved path escapes the workspace or accesses .git.
    """
    if not rel or not rel.strip():
        raise PolicyDenied("INVALID_PATH", "Path cannot be empty")

    ws_resolved = ws.resolve()

    # Reject UNC paths and cross-drive traversals immediately if they are explicit
    clean_rel = rel.replace("\\", "/")
    if clean_rel.startswith("//") or clean_rel.startswith("\\\\"):
        raise PolicyDenied("PATH_OUTSIDE_WORKSPACE", f"UNC paths not permitted: {rel!r}")

    # If rel is absolute, verify whether it targets workspace or an external path
    target = Path(rel)
    p = target.resolve() if target.is_absolute() else (ws / rel).resolve()

    # Verify containment within workspace
    try:
        rel_to_ws = p.relative_to(ws_resolved)
    except ValueError:
        raise PolicyDenied("PATH_OUTSIDE_WORKSPACE", f"Path {rel!r} resolves outside workspace {ws}") from None

    # Verify no .git internal component is accessed
    if any(part == ".git" for part in rel_to_ws.parts):
        raise PolicyDenied("GIT_INTERNALS", f"Path {rel!r} touches git internals")

    return p


def _matches_glob(rel_str: str, pattern: str) -> bool:
    """Check if relative path matches a glob pattern using pathlib.PurePath.match and fnmatch."""
    p = PurePath(rel_str)
    if p.match(pattern):
        return True
    name = p.name
    # Strip leading **/ if present for filename matching
    simple_pat = pattern.replace("**/", "")
    return bool(fnmatch.fnmatch(name, simple_pat) or fnmatch.fnmatch(rel_str, simple_pat))


def check_write_allowed(ws: Path, rel_path: str, plan_allows_lockfile: bool = False) -> None:
    """Enforce write-deny globs against targets in the workspace."""
    p = resolve_in_workspace(ws, rel_path)
    rel_str = p.relative_to(ws.resolve()).as_posix()

    for pattern in DEFAULT_WRITE_DENY:
        if plan_allows_lockfile and pattern in ("poetry.lock", "package-lock.json", "pnpm-lock.yaml"):
            continue
        if _matches_glob(rel_str, pattern):
            raise PolicyDenied("WRITE_DENIED", f"Write to {rel_path!r} is prohibited by policy ({pattern})")


def is_read_redacted(rel_path: str) -> bool:
    """Check if a file path matches sensitive read-redaction patterns."""
    clean_path = rel_path.replace("\\", "/")
    return any(_matches_glob(clean_path, pattern) for pattern in DEFAULT_READ_REDACT)


def redact_secrets(text: str) -> str:
    """Mask credentials and known secret tokens in text output."""
    redacted = text
    for pattern in SECRET_PATTERNS.values():
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_file_content(content: str) -> str:
    """Redact values in .env or configuration key-value files."""
    lines: list[str] = []
    for line in content.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _ = line.split("=", 1)
            lines.append(f"{k}=[REDACTED]")
        elif ":" in line and not line.strip().startswith("#"):
            k, _ = line.split(":", 1)
            lines.append(f"{k}: [REDACTED]")
        else:
            lines.append(redact_secrets(line))
    return "\n".join(lines)


def _pattern_matches(cmd_parts: list[str], pattern: str) -> bool:
    """Match command tokens against a pattern string supporting wildcards."""
    pat_parts = pattern.split()
    if not pat_parts:
        return False

    i = 0
    j = 0
    while i < len(cmd_parts) and j < len(pat_parts):
        pat_tok = pat_parts[j]
        if pat_tok == "*":
            # Wildcard matches everything to end of command
            return True
        if pat_tok.endswith("*"):
            prefix = pat_tok[:-1]
            if not cmd_parts[i].startswith(prefix):
                return False
            # If this is the last token in the pattern and ends with *, it consumes remaining args
            if j == len(pat_parts) - 1:
                return True
        elif fnmatch.fnmatch(cmd_parts[i], pat_tok):
            pass
        elif cmd_parts[i] != pat_tok:
            return False
        i += 1
        j += 1

    if j < len(pat_parts) and pat_parts[j] == "*":
        return True
    return i == len(cmd_parts) and j == len(pat_parts)


class CommandPolicy:
    """Evaluates command argv against allow, ask, and deny tiers."""

    def __init__(
        self,
        allow_patterns: list[str] | None = None,
        ask_patterns: list[str] | None = None,
        deny_patterns: list[str] | None = None,
    ) -> None:
        self.allow_patterns = allow_patterns if allow_patterns is not None else DEFAULT_ALLOW_PATTERNS
        self.ask_patterns = ask_patterns if ask_patterns is not None else DEFAULT_ASK_PATTERNS
        self.deny_patterns = deny_patterns if deny_patterns is not None else DEFAULT_DENY_PATTERNS

    def classify(
        self,
        argv: list[str],
        caller_role: str | None = None,
    ) -> Literal["allow", "ask"]:
        """Classify command into 'allow' or 'ask', or raise PolicyDenied if denied."""
        if not argv:
            raise PolicyDenied("EMPTY_COMMAND", "Command argv cannot be empty")

        is_python_c = (
            len(argv) >= 3
            and PurePath(argv[0]).stem.lower() in ("python", "python3", "py")
            and argv[1] == "-c"
        )

        # 1. Shell metacharacter rejection across all arguments
        for idx, arg in enumerate(argv):
            if is_python_c and idx == 2:
                # Python code string may use semicolons for statement separation
                if re.search(r"[&|`$<>\r\n]", arg):
                    raise PolicyDenied(
                        "SHELL_METACHARACTER",
                        f"Shell metacharacters forbidden in argument: {arg!r}",
                    )
                continue
            if METACHARACTER_RE.search(arg):
                raise PolicyDenied(
                    "SHELL_METACHARACTER",
                    f"Shell metacharacters forbidden in argument: {arg!r}",
                )

        # 2. Normalise first token (binary name, strip .exe on Windows)
        first_token = argv[0].replace("\\", "/")
        stem = PurePath(first_token).stem.lower()

        # Build normalized command token sequence
        normalized_argv = [stem, *argv[1:]]

        # Handle python alias resolution (python3 -> python, etc.)
        if normalized_argv[0] in ("python3", "py"):
            normalized_argv[0] = "python"

        # 3. Special handling for `python -c`
        if normalized_argv[0] == "python" and len(normalized_argv) > 1 and normalized_argv[1] == "-c":
            if caller_role not in ("verifier", "sentinel"):
                raise PolicyDenied(
                    "PYTHON_C_DENIED",
                    f"python -c execution is only permitted for Verifier and Sentinel (caller={caller_role})",
                )
            code = " ".join(normalized_argv[2:]) if len(normalized_argv) > 2 else ""
            # Inspect for forbidden module imports
            forbidden = ("os", "subprocess", "shutil", "sys.modules", "eval", "exec", "open")
            for f in forbidden:
                if re.search(r"\b" + re.escape(f) + r"\b", code):
                    raise PolicyDenied(
                        "PYTHON_C_SUSPICIOUS_IMPORT",
                        f"python -c code references forbidden symbol {f!r}",
                    )

        # 4. Check explicit deny patterns first
        for pat in self.deny_patterns:
            if _pattern_matches(normalized_argv, pat):
                raise PolicyDenied("COMMAND_DENIED", f"Command is explicitly denied: {' '.join(argv)}")

        # 5. Check ask tier (e.g. package installation)
        for pat in self.ask_patterns:
            if _pattern_matches(normalized_argv, pat):
                return "ask"

        # 6. Check allow tier
        for pat in self.allow_patterns:
            if _pattern_matches(normalized_argv, pat):
                return "allow"

        # 7. Default deny for everything else
        raise PolicyDenied(
            "COMMAND_NOT_ALLOWLISTED",
            f"Command is not in allowlist: {' '.join(argv)}",
        )


def _extract_asserts(tree: ast.AST) -> set[str]:
    """Collect canonical representations of all assert statements in an AST."""
    asserts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            with contextlib.suppress(Exception):
                asserts.add(ast.dump(node.test))
    return asserts


def _has_skip_or_xfail(tree: ast.AST) -> set[str]:
    """Find any pytest skip or xfail decorators or function calls."""
    markers: set[str] = set()
    for node in ast.walk(tree):
        # Check decorators
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                dec_str = ast.dump(decorator)
                if "skip" in dec_str or "xfail" in dec_str:
                    markers.add(f"decorator:{node.name}")
        # Check call expressions like pytest.skip()
        if isinstance(node, ast.Call):
            call_str = ast.dump(node.func)
            if "skip" in call_str or "xfail" in call_str:
                markers.add("call:skip_or_xfail")
    return markers


def check_test_edit_allowed(
    old_content: str,
    new_content: str,
    may_edit_tests: bool = False,
) -> None:
    """Verify that a modified test file does not weaken assertions or add skip/xfail markers.

    Adding new tests or additional assertions is permitted, but existing assertions
    must not be removed or altered without explicit authorization.
    """
    if may_edit_tests:
        return

    try:
        old_tree = ast.parse(old_content)
        new_tree = ast.parse(new_content)
    except SyntaxError:
        # If parsing fails due to syntax errors, allow it to be caught by the test runner/linter
        return

    old_asserts = _extract_asserts(old_tree)
    new_asserts = _extract_asserts(new_tree)

    # Check for removed or modified assertions
    missing_asserts = old_asserts - new_asserts
    if missing_asserts:
        raise PolicyDenied(
            "TEST_PROTECTION_ASSERTION_MODIFIED",
            f"Removed or modified {len(missing_asserts)} assert statement(s) without test authorization",
        )

    # Check for newly added skip or xfail markers
    old_markers = _has_skip_or_xfail(old_tree)
    new_markers = _has_skip_or_xfail(new_tree)
    added_markers = new_markers - old_markers
    if added_markers:
        raise PolicyDenied(
            "TEST_PROTECTION_SKIP_XFAIL_ADDED",
            f"Added skip/xfail markers ({added_markers}) without test authorization",
        )
