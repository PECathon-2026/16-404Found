"""Unit tests for security policy, path jail, command matching, and test protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.tools.policy import (
    CommandPolicy,
    PolicyDenied,
    check_test_edit_allowed,
    check_write_allowed,
    is_read_redacted,
    redact_file_content,
    redact_secrets,
    resolve_in_workspace,
)


def test_path_jail_traversal_denied(tmp_path: Path) -> None:
    """Relative traversal with .. escaping workspace must raise PolicyDenied."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, "../outside.txt")
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, "..\\outside.txt")
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_path_jail_absolute_outside_denied(tmp_path: Path) -> None:
    """Absolute paths outside workspace must raise PolicyDenied."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "external"
    outside.mkdir()

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, str(outside / "file.txt"))
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_path_jail_unc_denied(tmp_path: Path) -> None:
    """UNC network shares must raise PolicyDenied."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, "\\\\server\\share\\file.txt")
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, "//server/share/file.txt")
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_path_jail_git_internals_denied(tmp_path: Path) -> None:
    """Paths touching .git must raise PolicyDenied GIT_INTERNALS."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    git_dir = ws / ".git"
    git_dir.mkdir()

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, ".git/config")
    assert exc_info.value.code == "GIT_INTERNALS"

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, "sub/.git/HEAD")
    assert exc_info.value.code == "GIT_INTERNALS"


def test_path_jail_symlink_out_denied(tmp_path: Path) -> None:
    """Symlink pointing outside workspace must be resolved and denied."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    target = tmp_path / "outside_target.txt"
    target.write_text("outside", encoding="utf-8")

    link = ws / "symlink_escape"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted in this environment")

    with pytest.raises(PolicyDenied) as exc_info:
        resolve_in_workspace(ws, "symlink_escape")
    assert exc_info.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_path_jail_valid_paths_allowed(tmp_path: Path) -> None:
    """Valid nested paths inside workspace resolve correctly."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    sub = ws / "src"
    sub.mkdir()
    f = sub / "app.py"
    f.write_text("print('ok')", encoding="utf-8")

    resolved = resolve_in_workspace(ws, "src/app.py")
    assert resolved == f.resolve()


def test_write_deny_prohibits_protected_files(tmp_path: Path) -> None:
    """Protected files (.git, .env, pem, keys, workflows) cannot be written."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, ".env")
    assert exc.value.code == "WRITE_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, "config/.env.local")
    assert exc.value.code == "WRITE_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, "server.pem")
    assert exc.value.code == "WRITE_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, ".github/workflows/ci.yml")
    assert exc.value.code == "WRITE_DENIED"


def test_write_deny_lockfiles(tmp_path: Path) -> None:
    """Lockfiles are protected unless plan explicitly allows it."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, "poetry.lock", plan_allows_lockfile=False)
    assert exc.value.code == "WRITE_DENIED"

    # Permitted when plan_allows_lockfile=True
    check_write_allowed(ws, "poetry.lock", plan_allows_lockfile=True)


def test_is_read_redacted() -> None:
    """Sensitive patterns match for read redaction."""
    assert is_read_redacted(".env") is True
    assert is_read_redacted("deep/path/.env.production") is True
    assert is_read_redacted("certs/secret_key.txt") is True
    assert is_read_redacted("server.pem") is True
    assert is_read_redacted("src/index.ts") is False


def test_redact_file_content() -> None:
    """Configuration values in sensitive files are masked."""
    content = "DATABASE_URL=postgres://user:pass@localhost/db\nAPI_KEY=sk-12345678901234567890123456789012\nDEBUG=True"
    redacted = redact_file_content(content)
    assert "DATABASE_URL=[REDACTED]" in redacted
    assert "API_KEY=[REDACTED]" in redacted
    assert "sk-1234567890" not in redacted


def test_command_policy_allow_tier() -> None:
    """Known test, lint, and git inspection commands must be in allow tier."""
    policy = CommandPolicy()
    assert policy.classify(["pytest", "tests/"]) == "allow"
    assert policy.classify(["python", "-m", "pytest", "tests/"]) == "allow"
    assert policy.classify(["python", "-m", "ruff", "check", "."]) == "allow"
    assert policy.classify(["git", "status", "-s"]) == "allow"
    assert policy.classify(["git", "diff", "HEAD"]) == "allow"
    assert policy.classify(["npm", "test"]) == "allow"


def test_command_policy_ask_tier() -> None:
    """Package installation commands must require human approval (ask tier)."""
    policy = CommandPolicy()
    assert policy.classify(["pip", "install", "requests"]) == "ask"
    assert policy.classify(["python", "-m", "pip", "install", "fastapi"]) == "ask"
    assert policy.classify(["npm", "install", "lodash"]) == "ask"
    assert policy.classify(["npm", "ci"]) == "ask"


def test_command_policy_deny_tier() -> None:
    """Destructive, network, or privilege escalation commands are explicitly denied."""
    policy = CommandPolicy()

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["rm", "-rf", "build"])
    assert exc.value.code == "COMMAND_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["git", "push", "origin", "main"])
    assert exc.value.code == "COMMAND_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["git", "reset", "--hard", "HEAD~1"])
    assert exc.value.code == "COMMAND_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["curl", "https://api.external.com"])
    assert exc.value.code == "COMMAND_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["sudo", "apt", "update"])
    assert exc.value.code == "COMMAND_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["powershell", "-c", "dir"])
    assert exc.value.code == "COMMAND_DENIED"


def test_command_policy_metacharacter_rejection() -> None:
    """Shell metacharacters in arguments must be rejected immediately."""
    policy = CommandPolicy()

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["pytest", ";", "rm", "-rf", "/"])
    assert exc.value.code == "SHELL_METACHARACTER"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["pytest", "&&", "echo", "done"])
    assert exc.value.code == "SHELL_METACHARACTER"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["git", "status", "|", "grep", "M"])
    assert exc.value.code == "SHELL_METACHARACTER"


def test_command_policy_forbidden_flags_denied(tmp_path: Path) -> None:
    """R1 regression: Denylisted command flags that bypass jail or cause side effects are denied."""
    policy = CommandPolicy()
    ws = tmp_path / "workspace"
    ws.mkdir()

    # git --output / -o
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["git", "diff", "--output=C:/Users/Public/x"], workspace=ws)
    assert exc.value.code == "FORBIDDEN_FLAG"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["git", "log", "-o", "../escape.txt"], workspace=ws)
    assert exc.value.code == "FORBIDDEN_FLAG"

    # git -c (config injection)
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["git", "-c", "core.editor=calc", "status"], workspace=ws)
    assert exc.value.code == "FORBIDDEN_FLAG"

    # git --no-index
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["git", "diff", "--no-index", "a.txt", "b.txt"], workspace=ws)
    assert exc.value.code == "FORBIDDEN_FLAG"

    # pytest --basetemp / -p plugin injection
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["pytest", "--basetemp=C:/some/dir"], workspace=ws)
    assert exc.value.code == "FORBIDDEN_FLAG"

    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["pytest", "-p", "evil_plugin"], workspace=ws)
    assert exc.value.code == "FORBIDDEN_FLAG"

    # ruff --fix
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["ruff", "check", "--fix", "."], workspace=ws)
    assert exc.value.code == "FORBIDDEN_FLAG"


def test_command_policy_argument_path_jail(tmp_path: Path) -> None:
    """R1 regression: Command path arguments outside workspace are rejected."""
    policy = CommandPolicy()
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "tests").mkdir()
    (ws / "tests" / "test_a.py").write_text("def test_ok(): pass", encoding="utf-8")

    # Outside workspace path
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["pytest", "../external_test.py"], workspace=ws)
    assert exc.value.code == "PATH_OUTSIDE_WORKSPACE"

    # Valid in-workspace pytest node id
    res = policy.classify(["pytest", "tests/test_a.py::test_ok"], workspace=ws)
    assert res == "allow"


def test_command_policy_npx_jest_removed() -> None:
    """R1 regression: npx jest is not allowlisted."""
    policy = CommandPolicy()
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["npx", "jest"])
    assert exc.value.code == "COMMAND_NOT_ALLOWLISTED"


def test_command_policy_python_c_removed() -> None:
    """R4 regression: python -c is dropped from allowlist and rejected."""
    policy = CommandPolicy()
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["python", "-c", "print(1)"])
    assert exc.value.code == "COMMAND_NOT_ALLOWLISTED"


def test_command_policy_unmatched_default_deny() -> None:
    """Unmatched commands are denied by default."""
    policy = CommandPolicy()
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["cat", "passwords.txt"])
    assert exc.value.code == "COMMAND_NOT_ALLOWLISTED"


def test_test_assertion_protection() -> None:
    """Removing or weakening assertions or adding skip markers is blocked without authorization."""
    old_test = """
def test_calc():
    assert add(1, 2) == 3
    assert subtract(5, 2) == 3
"""

    # 1. Removing an assertion -> Denied
    tampered_remove = """
def test_calc():
    assert add(1, 2) == 3
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_test, tampered_remove, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # 2. Modifying an assertion -> Denied
    tampered_change = """
def test_calc():
    assert add(1, 2) == 3
    assert subtract(5, 2) == 4
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_test, tampered_change, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # 3. Adding @pytest.mark.skip -> Denied
    tampered_skip = """
import pytest

@pytest.mark.skip(reason="broken")
def test_calc():
    assert add(1, 2) == 3
    assert subtract(5, 2) == 3
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_test, tampered_skip, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_SKIP_XFAIL_ADDED"

    # 4. Adding new test or new assertion -> Allowed
    valid_addition = """
def test_calc():
    assert add(1, 2) == 3
    assert subtract(5, 2) == 3
    assert multiply(2, 3) == 6

def test_new_case():
    assert True
"""
    check_test_edit_allowed(old_test, valid_addition, may_edit_tests=False)

    # 5. When may_edit_tests is True -> Allowed
    check_test_edit_allowed(old_test, tampered_remove, may_edit_tests=True)


def test_test_assertion_protection_multiset_and_reachability() -> None:
    """R5 regression: Multiset comparison, unreachable asserts, and method calls."""
    # Multiset: removing one of two identical assertions
    old_dupes = """
def test_dupes():
    assert x == 1
    assert x == 1
"""
    new_single = """
def test_dupes():
    assert x == 1
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_dupes, new_single, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # Moving assert under constant-false if
    old_valid = """
def test_fn():
    assert compute() == 42
"""
    under_if_false = """
def test_fn():
    if False:
        assert compute() == 42
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_valid, under_if_false, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # Moving assert after return
    after_return = """
def test_fn():
    return
    assert compute() == 42
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_valid, after_return, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # Removing pytest.raises
    old_raises = """
import pytest

def test_err():
    with pytest.raises(ValueError):
        raise ValueError("bad")
"""
    new_no_raises = """
def test_err():
    pass
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_raises, new_no_raises, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # Removing self.assertEqual
    old_unittest = """
def test_case(self):
    self.assertEqual(a, b)
"""
    new_unittest = """
def test_case(self):
    pass
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_unittest, new_unittest, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"

    # Removing/renaming test function
    renamed_fn = """
def not_a_test():
    assert compute() == 42
"""
    with pytest.raises(PolicyDenied) as exc:
        check_test_edit_allowed(old_valid, renamed_fn, may_edit_tests=False)
    assert exc.value.code == "TEST_PROTECTION_ASSERTION_MODIFIED"


def test_secret_redaction_patterns() -> None:
    """Outputs containing tokens, keys, and connection strings are masked."""
    text = (
        "AWS key: AKIAIOSFODNN7EXAMPLE\n"
        "Anthropic: sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789\n"
        "OpenAI: sk-1234567890abcdef1234567890abcdef\n"
        "GitHub: ghp_1234567890abcdef1234567890abcdef1234\n"
        "Conn: postgres://admin:secretpassword@localhost:5432/mydb\n"
        "Assign: api_key = 'abcdef0123456789'\n"
    )
    redacted = redact_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "sk-ant-api03" not in redacted
    assert "sk-1234567890abcdef" not in redacted
    assert "ghp_1234567890" not in redacted
    assert "secretpassword" not in redacted
    assert "abcdef0123456789" not in redacted
    assert "[REDACTED]" in redacted
