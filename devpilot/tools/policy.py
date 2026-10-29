"""Security policy enforcement for filesystem access, command execution, and test integrity.

Provides:
- Filesystem path jail with symlink, traversal, and UNC/drive letter containment checks.
- Default-deny command classification across allow / ask / deny tiers with metacharacter and flag rejection.
- AST-level test protection that prevents removing/altering existing assertions or adding skip/xfail markers.
- Secret redaction for tool outputs and sensitive configuration files.
"""

from __future__ import annotations

import ast
import collections
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
    "private_key": re.compile(
        r"-----BEGIN (?:RSA|EC|OPENSSH|PRIVATE) KEY-----[\s\S]*?-----END (?:RSA|EC|OPENSSH|PRIVATE) KEY-----"
    ),
    "generic_assign": re.compile(
        r"(?i)(api[_-]?key|secret|passw(?:or)?d|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ),
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
    "git status *",
    "git diff *",
    "git log *",
    "git show *",
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

FORBIDDEN_FLAG_PREFIXES: tuple[str, ...] = (
    "--output",
    "--no-index",
    "--basetemp",
    "--rootdir",
    "--confcutdir",
    "--fix",
    "--unsafe-fixes",
    "--pyargs",
    "--exec-path",
    "--git-dir",
    "--work-tree",
    "--cache-dir",
)


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

    clean_rel = rel.replace("\\", "/")
    if clean_rel.startswith("//") or clean_rel.startswith("\\\\"):
        raise PolicyDenied("PATH_OUTSIDE_WORKSPACE", f"UNC paths not permitted: {rel!r}")

    target = Path(rel)
    p = target.resolve() if target.is_absolute() else (ws / rel).resolve()

    try:
        rel_to_ws = p.relative_to(ws_resolved)
    except ValueError:
        raise PolicyDenied(
            "PATH_OUTSIDE_WORKSPACE", f"Path {rel!r} resolves outside workspace {ws}"
        ) from None

    if any(part == ".git" for part in rel_to_ws.parts):
        raise PolicyDenied("GIT_INTERNALS", f"Path {rel!r} touches git internals")

    return p


def _matches_glob(rel_str: str, pattern: str) -> bool:
    """Check if relative path matches a glob pattern using pathlib.PurePath.match and fnmatch."""
    p = PurePath(rel_str)
    if p.match(pattern):
        return True
    name = p.name
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
            return True
        if pat_tok.endswith("*"):
            prefix = pat_tok[:-1]
            if not cmd_parts[i].startswith(prefix):
                return False
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
        workspace: Path | None = None,
    ) -> Literal["allow", "ask"]:
        """Classify command into 'allow' or 'ask', or raise PolicyDenied if denied."""
        if not argv:
            raise PolicyDenied("EMPTY_COMMAND", "Command argv cannot be empty")

        # 1. Shell metacharacter rejection across all arguments
        for arg in argv:
            if METACHARACTER_RE.search(arg):
                raise PolicyDenied(
                    "SHELL_METACHARACTER",
                    f"Shell metacharacters forbidden in argument: {arg!r}",
                )

        # 2. Normalise first token (binary name, strip .exe on Windows)
        first_token = argv[0].replace("\\", "/")
        stem = PurePath(first_token).stem.lower()

        normalized_argv = [stem, *argv[1:]]
        if normalized_argv[0] in ("python3", "py"):
            normalized_argv[0] = "python"

        # 3. Denylist forbidden flags (R1)
        is_git = normalized_argv[0] == "git"
        is_pytest = (
            normalized_argv[0] == "pytest"
            or (normalized_argv[0] == "python" and len(normalized_argv) > 2 and normalized_argv[1:3] == ["-m", "pytest"])
        )

        for arg in argv[1:]:
            if is_git and (arg in ("-o", "-c") or arg.startswith(("-o=", "-c="))):
                raise PolicyDenied("FORBIDDEN_FLAG", f"Flag {arg!r} is forbidden on git commands")
            if is_pytest and (arg == "-p" or arg.startswith("-p=")):
                raise PolicyDenied("FORBIDDEN_FLAG", f"Plugin loading flag {arg!r} is forbidden on pytest")

            for prefix in FORBIDDEN_FLAG_PREFIXES:
                if arg == prefix or arg.startswith(prefix + "=") or arg.startswith(prefix):
                    raise PolicyDenied("FORBIDDEN_FLAG", f"Flag {arg!r} is forbidden by command policy")

        # 4. Check that path arguments resolve strictly inside workspace (R1)
        if workspace is not None:
            for arg in argv[1:]:
                if arg.startswith("-"):
                    continue
                candidate = arg.split("::", 1)[0]
                if (
                    "/" in candidate
                    or "\\" in candidate
                    or candidate.startswith(".")
                    or (workspace / candidate).exists()
                ):
                    resolve_in_workspace(workspace, candidate)

        # 5. Check explicit deny patterns first
        for pat in self.deny_patterns:
            if _pattern_matches(normalized_argv, pat):
                raise PolicyDenied("COMMAND_DENIED", f"Command is explicitly denied: {' '.join(argv)}")

        # 6. Check ask tier (e.g. package installation)
        for pat in self.ask_patterns:
            if _pattern_matches(normalized_argv, pat):
                return "ask"

        # 7. Check allow tier
        for pat in self.allow_patterns:
            if _pattern_matches(normalized_argv, pat):
                return "allow"

        # 8. Default deny for everything else
        raise PolicyDenied(
            "COMMAND_NOT_ALLOWLISTED",
            f"Command is not in allowlist: {' '.join(argv)}",
        )


def _is_const_false(node: ast.AST) -> bool:
    """Determine if an AST condition is statically False."""
    if isinstance(node, ast.Constant):
        return not bool(node.value)
    return bool(isinstance(node, ast.Name) and node.id in ("False", "None"))


def _is_const_true(node: ast.AST) -> bool:
    """Determine if an AST condition is statically True."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    return bool(isinstance(node, ast.Name) and node.id == "True")


def _extract_stmts_asserts(stmts: list[ast.stmt]) -> list[str]:
    """Extract reachable assertions from a statement sequence, stopping after return/raise."""
    result: list[str] = []
    for stmt in stmts:
        if isinstance(stmt, (ast.Return, ast.Raise)):
            break
        if isinstance(stmt, ast.Assert):
            with contextlib.suppress(Exception):
                result.append(f"assert:{ast.dump(stmt.test)}")
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            is_assert_call = (
                (isinstance(call.func, ast.Attribute) and call.func.attr.startswith("assert"))
                or (isinstance(call.func, ast.Name) and call.func.id.startswith("assert"))
            )
            if is_assert_call:
                with contextlib.suppress(Exception):
                    result.append(f"call:{ast.dump(call)}")
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                expr = item.context_expr
                if isinstance(expr, ast.Call):
                    fn_name = ""
                    if isinstance(expr.func, ast.Name):
                        fn_name = expr.func.id
                    elif isinstance(expr.func, ast.Attribute):
                        fn_name = expr.func.attr
                    if fn_name in ("raises", "assertRaises") or "raises" in fn_name.lower():
                        with contextlib.suppress(Exception):
                            result.append(f"raises:{ast.dump(expr)}")
            result.extend(_extract_stmts_asserts(stmt.body))
        elif isinstance(stmt, ast.If):
            if _is_const_false(stmt.test):
                result.extend(_extract_stmts_asserts(stmt.orelse))
            elif _is_const_true(stmt.test):
                result.extend(_extract_stmts_asserts(stmt.body))
            else:
                result.extend(_extract_stmts_asserts(stmt.body))
                result.extend(_extract_stmts_asserts(stmt.orelse))
        elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.Try)):
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, list):
                    result.extend(_extract_stmts_asserts([s for s in child if isinstance(s, ast.stmt)]))
                elif isinstance(child, ast.stmt):
                    result.extend(_extract_stmts_asserts([child]))
    return result


def _collect_test_info(tree: ast.AST) -> tuple[dict[str, list[str]], collections.Counter[str]]:
    """Returns (test_function_name -> list of asserts, multiset of all asserts)."""
    test_funcs: dict[str, list[str]] = {}
    all_asserts: collections.Counter[str] = collections.Counter()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name.startswith("test_") or node.name.endswith("_test")
        ):
            fn_asserts = _extract_stmts_asserts(node.body)
            test_funcs[node.name] = fn_asserts
            all_asserts.update(fn_asserts)

    if isinstance(tree, ast.Module):
        top_asserts = _extract_stmts_asserts(
            [s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        )
        all_asserts.update(top_asserts)

    return test_funcs, all_asserts


def _has_skip_or_xfail(tree: ast.AST) -> set[str]:
    """Find any pytest skip or xfail decorators or function calls."""
    markers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                dec_str = ast.dump(decorator)
                if "skip" in dec_str or "xfail" in dec_str:
                    markers.add(f"decorator:{node.name}")
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
        return

    old_funcs, old_asserts = _collect_test_info(old_tree)
    new_funcs, new_asserts = _collect_test_info(new_tree)

    # Check for removed or renamed test functions
    removed_funcs = set(old_funcs.keys()) - set(new_funcs.keys())
    if removed_funcs:
        raise PolicyDenied(
            "TEST_PROTECTION_ASSERTION_MODIFIED",
            f"Test function(s) {sorted(removed_funcs)} were removed or renamed without authorization",
        )

    # Multiset comparison of assertions
    missing_asserts = old_asserts - new_asserts
    if missing_asserts:
        count = sum(missing_asserts.values())
        raise PolicyDenied(
            "TEST_PROTECTION_ASSERTION_MODIFIED",
            f"Removed or modified {count} assert statement(s) without test authorization",
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
