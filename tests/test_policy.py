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

    resolved = resolve_in_workspace(ws, "src/main.py")
    assert resolved == (sub / "main.py").resolve()


def test_write_deny_globs(tmp_path: Path) -> None:
    """Write-deny patterns must block sensitive files and workflows."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # .env files
    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, ".env")
    assert exc.value.code == "WRITE_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, "sub/.env.production")
    assert exc.value.code == "WRITE_DENIED"

    # workflows
    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, ".github/workflows/ci.yml")
    assert exc.value.code == "WRITE_DENIED"

    # keys
    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, "id_rsa")
    assert exc.value.code == "WRITE_DENIED"

    with pytest.raises(PolicyDenied) as exc:
        check_write_allowed(ws, "certs/server.pem")
    assert exc.value.code == "WRITE_DENIED"

    # Lockfiles
    with pytest.raises(PolicyDenied):
        check_write_allowed(ws, "poetry.lock", plan_allows_lockfile=False)

    # Allowed with flag
    check_write_allowed(ws, "poetry.lock", plan_allows_lockfile=True)

    # Normal files allowed
    check_write_allowed(ws, "src/calculator.py")


def test_read_redact_globs() -> None:
    """Read redaction matches sensitive file names."""
    assert is_read_redacted(".env") is True
    assert is_read_redacted(".env.local") is True
    assert is_read_redacted("config/my_secret_keys.json") is True
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


def test_command_policy_python_c_security() -> None:
    """python -c is restricted to verifier/sentinel and forbids dangerous imports."""
    policy = CommandPolicy()

    # Denied for samurai
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["python", "-c", "print(1)"], caller_role="samurai")
    assert exc.value.code == "PYTHON_C_DENIED"

    # Allowed for verifier when safe
    assert policy.classify(["python", "-c", "assert 1 + 1 == 2"], caller_role="verifier") == "allow"

    # Forbidden import denied even for verifier
    with pytest.raises(PolicyDenied) as exc:
        policy.classify(["python", "-c", "import os; os.system('dir')"], caller_role="verifier")
    assert exc.value.code == "PYTHON_C_SUSPICIOUS_IMPORT"


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
