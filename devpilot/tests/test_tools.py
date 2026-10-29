"""Tests for tools/safety.py, file_tools.py, command_tool.py, secret_scan.py."""

from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.safety import check_path, check_command, SafetyError, is_command_blocked
from tools.file_tools import read_file, edit_file, search_code, list_files
from tools.command_tool import run_command
from tools.secret_scan import scan_file, scan_directory


# ---------- Safety: path checks ----------


def test_path_allows_valid_path(tmp_path):
    """Valid path inside workspace is allowed."""
    target = tmp_path / "foo.py"
    target.touch()
    resolved = check_path(str(target), str(tmp_path))
    assert resolved == target.resolve()


def test_path_blocks_dotdot(tmp_path):
    """Path with .. is blocked."""
    with pytest.raises(SafetyError, match="traversal"):
        check_path(str(tmp_path / ".." / "escape.py"), str(tmp_path))


def test_path_blocks_outside_workspace(tmp_path, tmp_path_factory):
    """Absolute path outside workspace is blocked."""
    other = tmp_path_factory.mktemp("other")
    outside = other / "secret.py"
    outside.touch()
    with pytest.raises(SafetyError, match="outside workspace"):
        check_path(str(outside), str(tmp_path))


def test_path_blocks_symlink_escape(tmp_path, tmp_path_factory):
    """Symlink pointing outside workspace is blocked."""
    other = tmp_path_factory.mktemp("escape_target")
    link = tmp_path / "link.py"
    link.symlink_to(other / "secret.py")
    with pytest.raises(SafetyError):
        check_path(str(link), str(tmp_path))


# ---------- Safety: command checks ----------


def test_command_allows_pytest():
    """pytest is on the allow list."""
    check_command("pytest tests/")  # should not raise


def test_command_allows_git_diff():
    """git diff is on the allow list."""
    check_command("git diff")


def test_command_blocks_rm():
    """rm is blocked."""
    with pytest.raises(SafetyError, match="Blocked"):
        check_command("rm -rf /")


def test_command_blocks_curl():
    """curl is blocked."""
    with pytest.raises(SafetyError, match="Blocked"):
        check_command("curl https://evil.com")


def test_command_blocks_sudo():
    """sudo is blocked."""
    with pytest.raises(SafetyError, match="Blocked"):
        check_command("sudo ls")


def test_command_blocks_env_access():
    """.env file access is blocked."""
    with pytest.raises(SafetyError):
        check_command("cat .env")


def test_is_command_blocked_true():
    """is_command_blocked returns True for blocked commands."""
    assert is_command_blocked("rm -rf /")
    assert is_command_blocked("curl https://example.com")


def test_is_command_blocked_false():
    """is_command_blocked returns False for allowed commands."""
    assert not is_command_blocked("pytest tests/")
    assert not is_command_blocked("git diff")


# ---------- run_command safety integration ----------


def test_run_command_blocks_rm(tmp_path):
    """run_command marks rm as blocked and does not execute."""
    result = run_command("rm -rf /", str(tmp_path))
    assert result["blocked"] is True
    assert result["exit_code"] == 126


def test_run_command_blocks_curl(tmp_path):
    """run_command marks curl as blocked."""
    result = run_command("curl https://example.com", str(tmp_path))
    assert result["blocked"] is True


def test_run_command_simulate_missing(tmp_path):
    """run_command returns exit 127 when tool is simulated missing."""
    result = run_command("pytest tests/", str(tmp_path), simulate_missing="pytest")
    assert result["exit_code"] == 127
    assert "command not found" in result["stderr"]


def test_run_command_runs_ls(tmp_path):
    """run_command can run ls."""
    result = run_command("ls", str(tmp_path))
    assert not result["blocked"]
    assert result["exit_code"] == 0


# ---------- file_tools ----------


def test_read_file_ok(tmp_path):
    """read_file returns file content."""
    f = tmp_path / "hello.py"
    f.write_text("print('hello')")
    assert read_file(str(f), str(tmp_path)) == "print('hello')"


def test_read_file_outside_workspace(tmp_path, tmp_path_factory):
    """read_file blocks paths outside workspace."""
    other = tmp_path_factory.mktemp("other")
    f = other / "secret.txt"
    f.write_text("secret")
    with pytest.raises(SafetyError):
        read_file(str(f), str(tmp_path))


def test_edit_file_creates(tmp_path):
    """edit_file creates a new file."""
    target = tmp_path / "new_file.py"
    edit_file(str(target), "x = 1", str(tmp_path))
    assert target.read_text() == "x = 1"


def test_list_files(tmp_path):
    """list_files returns relative paths."""
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.txt").write_text("")
    files = list_files(str(tmp_path), "*.py")
    assert "a.py" in files
    assert "b.txt" not in files


def test_search_code(tmp_path):
    """search_code finds pattern in files."""
    f = tmp_path / "code.py"
    f.write_text("def add_coupon(code):\n    pass\n")
    results = search_code("add_coupon", str(tmp_path))
    assert len(results) == 1
    assert results[0]["line"] == 1


# ---------- secret_scan ----------


def test_secret_scan_finds_key(tmp_path):
    """scan_file finds a hardcoded API key."""
    f = tmp_path / "config.py"
    f.write_text('PAYMENT_API_KEY = "sk_live_FAKE1234567890"\n')
    findings = scan_file(str(f))
    assert len(findings) >= 1
    types = [r["pattern_type"] for r in findings]
    assert "stripe_live_key" in types or "hardcoded_secret" in types


def test_secret_scan_finds_key_in_mini_shop():
    """scan_directory finds the key planted in mini_shop/config.py."""
    mini_shop = Path(__file__).parent.parent / "demo_repos" / "mini_shop"
    if not mini_shop.exists():
        pytest.skip("mini_shop not found")
    findings = scan_directory(str(mini_shop))
    types = [r["pattern_type"] for r in findings]
    assert "stripe_live_key" in types or "hardcoded_secret" in types


def test_secret_scan_finds_eval(tmp_path):
    """scan_file detects eval() usage."""
    f = tmp_path / "unsafe.py"
    f.write_text('result = eval(user_input)\n')
    findings = scan_file(str(f))
    assert any(r["pattern_type"] == "use_of_eval" for r in findings)


def test_secret_scan_no_false_positives(tmp_path):
    """scan_file does not flag clean code."""
    f = tmp_path / "clean.py"
    f.write_text('def add(a, b):\n    return a + b\n')
    findings = scan_file(str(f))
    assert findings == []
