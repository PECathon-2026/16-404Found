"""Unit tests for GitWorkspaces worktree lifecycle and isolation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devpilot.workspace.git_worktrees import GitWorkspaces, parse_diff_hunks


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)

    src = path / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "target_repo"
    _init_git_repo(repo_dir)
    return repo_dir


@pytest.mark.asyncio
async def test_workspace_creation_and_baseline(test_repo: Path, tmp_path: Path) -> None:
    """GitWorkspaces creates main and baseline worktrees isolated from target repo."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)

    main_path = await ws.create_main(test_repo, "M-001")
    assert main_path.exists()
    assert (main_path / "src" / "app.py").exists()

    baseline_path = await ws.create_baseline()
    assert baseline_path.exists()
    assert (baseline_path / "src" / "app.py").exists()

    # Verify path lookup
    assert await ws.path("main") == main_path
    assert await ws.path("baseline") == baseline_path


@pytest.mark.asyncio
async def test_workspace_fork_and_isolation(test_repo: Path, tmp_path: Path) -> None:
    """Fork creates an isolated sibling worktree; edits do not leak."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    await ws.create_main(test_repo, "M-002")
    await ws.create_baseline()

    cand_path = await ws.fork("cand-A", from_ref="main")
    assert cand_path.exists()

    # Modify file in cand-A
    (cand_path / "src" / "app.py").write_text("def main():\n    return 100\n", encoding="utf-8")

    # Verify main and baseline remain unchanged
    main_content = (await ws.path("main") / "src" / "app.py").read_text(encoding="utf-8")
    base_content = (await ws.path("baseline") / "src" / "app.py").read_text(encoding="utf-8")

    assert "return 42" in main_content
    assert "return 42" in base_content


@pytest.mark.asyncio
async def test_workspace_diff_and_tree_sha(test_repo: Path, tmp_path: Path) -> None:
    """tree_sha calculates tree hash without modifying user index, diff shows changes."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-003")
    await ws.create_baseline()

    # Modify file in main
    (main_path / "src" / "app.py").write_text("def main():\n    return 99\n", encoding="utf-8")

    sha = await ws.tree_sha("main")
    assert len(sha) == 40

    diff_text = await ws.diff("main", against="baseline")
    assert "+    return 99" in diff_text
    assert "-    return 42" in diff_text


@pytest.mark.asyncio
async def test_workspace_hunk_parsing(test_repo: Path, tmp_path: Path) -> None:
    """hunks parses unified diff into stable IDs with start and length metadata."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-004")
    await ws.create_baseline()

    (main_path / "src" / "app.py").write_text(
        "def main():\n    x = 10\n    return x * 2\n", encoding="utf-8"
    )

    hunk_list = await ws.hunks("main")
    assert len(hunk_list) >= 1
    h1 = hunk_list[0]
    assert h1["id"] == "H1"
    assert "app.py" in h1["path"]
    assert h1["old_start"] >= 1
    assert "patch" in h1


@pytest.mark.asyncio
async def test_workspace_checkpoint_and_rollback(test_repo: Path, tmp_path: Path) -> None:
    """checkpoint creates a git commit; rollback restores that exact commit."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-005")

    # Commit initial edit
    (main_path / "src" / "app.py").write_text("def main():\n    return 10\n", encoding="utf-8")
    sha1 = await ws.checkpoint("attempt 1", ref="main")

    # Make second bad edit
    (main_path / "src" / "app.py").write_text("broken code\n", encoding="utf-8")
    (main_path / "untracked.py").write_text("untracked\n", encoding="utf-8")

    # Roll back to sha1
    await ws.rollback(sha1, ref="main")

    restored_text = (main_path / "src" / "app.py").read_text(encoding="utf-8")
    assert "return 10" in restored_text
    assert not (main_path / "untracked.py").exists()


@pytest.mark.asyncio
async def test_workspace_adopt_candidate(test_repo: Path, tmp_path: Path) -> None:
    """adopt applies candidate worktree changes to main and creates a checkpoint."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-006")
    cand_path = await ws.fork("cand-winner", from_ref="main")

    (cand_path / "src" / "app.py").write_text("def main():\n    return 'winner'\n", encoding="utf-8")

    await ws.adopt("cand-winner")

    main_text = (main_path / "src" / "app.py").read_text(encoding="utf-8")
    assert "return 'winner'" in main_text


@pytest.mark.asyncio
async def test_workspace_apply_to_clean_target(test_repo: Path, tmp_path: Path) -> None:
    """apply_to_target fast-forwards mission changes into clean target repository."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-007")

    (main_path / "src" / "app.py").write_text("def main():\n    return 'applied'\n", encoding="utf-8")
    await ws.checkpoint("ready for apply", ref="main")

    res = await ws.apply_to_target()
    assert len(res) == 40

    target_text = (test_repo / "src" / "app.py").read_text(encoding="utf-8")
    assert "return 'applied'" in target_text


@pytest.mark.asyncio
async def test_workspace_apply_refuses_dirty_target(test_repo: Path, tmp_path: Path) -> None:
    """apply_to_target refuses to modify target repository if it has uncommitted changes."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-008")

    (main_path / "src" / "app.py").write_text("def main():\n    return 'new'\n", encoding="utf-8")
    await ws.checkpoint("ready for apply", ref="main")

    # Dirty the target repo
    (test_repo / "dirty_user_edit.txt").write_text("user is working here", encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info:
        await ws.apply_to_target()
    assert "uncommitted modifications" in str(exc_info.value)


@pytest.mark.asyncio
async def test_workspace_non_git_target(tmp_path: Path) -> None:
    """Non-git directories are automatically initialized into a synthetic git repo."""
    plain_dir = tmp_path / "plain_project"
    plain_dir.mkdir()
    (plain_dir / "calc.py").write_text("x = 1\n", encoding="utf-8")

    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(plain_dir, "M-009")

    assert main_path.exists()
    assert (main_path / "calc.py").exists()
    assert ws.is_synthetic_git is True


def test_diff_hunk_parser_standalone() -> None:
    """Test parse_diff_hunks on multi-file diff with various line lengths."""
    raw_diff = """diff --git a/pkg/a.py b/pkg/a.py
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -10,2 +10,3 @@
-old line 1
-old line 2
+new line 1
+new line 2
+new line 3
diff --git a/pkg/b.py b/pkg/b.py
--- a/pkg/b.py
+++ b/pkg/b.py
@@ -5 +5,2 @@
-one line
+two lines
+extra
"""
    hunks = parse_diff_hunks(raw_diff)
    assert len(hunks) == 2
    assert hunks[0]["id"] == "H1"
    assert hunks[0]["path"] == "pkg/a.py"
    assert hunks[0]["old_start"] == 10
    assert hunks[0]["old_len"] == 2
    assert hunks[0]["new_len"] == 3

    assert hunks[1]["id"] == "H2"
    assert hunks[1]["path"] == "pkg/b.py"
    assert hunks[1]["old_start"] == 5
    assert hunks[1]["old_len"] == 1
    assert hunks[1]["new_len"] == 2


# --------------------------------------------------------------------------------------
# R1-R4 and Nits Regression Tests
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r1_target_git_config_never_overwritten(test_repo: Path, tmp_path: Path) -> None:
    """R1 regression: DevPilot must never modify target repo's git config."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-R1")
    await ws.create_baseline()

    (main_path / "src" / "app.py").write_text("def main(): return 'test'\n", encoding="utf-8")
    await ws.checkpoint("checkpoint without config change", ref="main")

    # Check local git config of target repo
    res = subprocess.run(
        ["git", "config", "--local", "--get", "user.name"],
        cwd=test_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "TestUser"


@pytest.mark.asyncio
async def test_r2_non_git_target_receives_applied_changes(tmp_path: Path) -> None:
    """R2 regression: Non-git target directory actually receives modified and created files."""
    plain_dir = tmp_path / "plain_app"
    plain_dir.mkdir()
    (plain_dir / "calc.py").write_text("x = 10\n", encoding="utf-8")
    (plain_dir / "old_to_delete.txt").write_text("delete me\n", encoding="utf-8")

    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(plain_dir, "M-R2")
    await ws.create_baseline()

    # Modify calc.py, delete old_to_delete.txt, add new_file.py
    (main_path / "calc.py").write_text("x = 999\n", encoding="utf-8")
    (main_path / "old_to_delete.txt").unlink()
    (main_path / "new_file.py").write_text("new = True\n", encoding="utf-8")
    await ws.checkpoint("ready for apply", ref="main")

    sha = await ws.apply_to_target()
    assert len(sha) == 40

    # Verify changes landed directly in plain_dir
    assert (plain_dir / "calc.py").read_text(encoding="utf-8") == "x = 999\n"
    assert (plain_dir / "new_file.py").read_text(encoding="utf-8") == "new = True\n"
    assert not (plain_dir / "old_to_delete.txt").exists()


@pytest.mark.asyncio
async def test_r3_dirty_target_baseline_and_main_match(test_repo: Path, tmp_path: Path) -> None:
    """R3 regression: When target is dirty, baseline and main start from the identical snapshot."""
    # Dirty the target repo before mission starts
    (test_repo / "src" / "app.py").write_text("def main(): return 'dirty'\n", encoding="utf-8")
    (test_repo / "untracked_user.txt").write_text("untracked edit\n", encoding="utf-8")

    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    await ws.create_main(test_repo, "M-R3")
    await ws.create_baseline()

    # Diffs between main and baseline at start must be completely empty!
    diff_init = await ws.diff("main", against="baseline")
    assert diff_init.strip() == ""
    assert ws.dirty_at_start is True


@pytest.mark.asyncio
async def test_r4_cleanup_removes_worktrees(test_repo: Path, tmp_path: Path) -> None:
    """R4 regression: cleanup removes all worktrees and prunes git references."""
    runs_dir = tmp_path / "runs"
    ws = GitWorkspaces(runs_dir=runs_dir)
    main_path = await ws.create_main(test_repo, "M-R4")
    base_path = await ws.create_baseline()
    cand_path = await ws.fork("cand-test", from_ref="main")

    assert main_path.exists()
    assert base_path.exists()
    assert cand_path.exists()

    await ws.cleanup(keep_branch=True)

    assert not main_path.exists()
    assert not base_path.exists()
    assert not cand_path.exists()

    # Verify git worktree list on target repo
    res = subprocess.run(
        ["git", "worktree", "list"],
        cwd=test_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "M-R4" not in res.stdout


def test_nits_diff_hunk_quoted_paths_and_renames() -> None:
    """Nits: parse_diff_hunks handles quoted spaces in paths and renames."""
    raw_diff = """diff --git "a/path with space/file.py" "b/path with space/file.py"
--- "a/path with space/file.py"
+++ "b/path with space/file.py"
@@ -1 +1 @@
-old
+new
diff --git a/old_name.py b/renamed.py
similarity index 90%
rename from old_name.py
rename to renamed.py
--- a/old_name.py
+++ b/renamed.py
@@ -10 +10 @@
-prev
+updated
"""
    hunks = parse_diff_hunks(raw_diff)
    assert len(hunks) == 2
    assert hunks[0]["path"] == "path with space/file.py"
    assert hunks[1]["path"] == "renamed.py"
