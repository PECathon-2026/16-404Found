# WP-G03 — Git Workspaces
**Status:** ready-for-review
**Branch:** wp/g03-workspaces   **Commits:** 363b559

## What I built
- `devpilot/workspace/git_worktrees.py`: `GitWorkspaces` implementing `ports.Workspaces` protocol:
  - Standard worktree layout in `runs/<mid>/ws/main`, `ws/baseline`, `ws/cand-A..C`, and `ws/scratch-*`.
  - Non-git target support: automatically copies repository files (respecting ignores), runs `git init`, and creates `devpilot baseline` commit.
  - Dirty target handling: snapshots uncommitted index and working tree modifications at mission start using `git stash create` without altering the user's work tree.
  - Temporary index hashing (`tree_sha`): isolates `git add -A` and `git write-tree` using `GIT_INDEX_FILE`, guaranteeing the user index is untouched.
  - Structured hunk parser (`parse_diff_hunks`): parses `git diff -U0` output into stable hunk dictionaries (`H1`, `H2`...) containing path, old/new line ranges, and unified patch text.
  - Checkpoint and rollback: `checkpoint` commits to `devpilot/<mid>` with message `devpilot: <label>`; `rollback` cleanly runs `git reset --hard` and `git clean -fd` inside the target worktree only.
  - Tournament winner adoption (`adopt`): applies candidate's tree directly onto `main` worktree and creates an adoption checkpoint.
  - Target application (`apply_to_target`): verifies target repository is clean (refuses if dirty with clear message), performs fast-forward merge `git merge --ff-only devpilot/<mid>`.
- Tests (`tests/test_workspaces.py`):
  - 10 tests verifying creation, baseline isolation, sibling forks, temporary index calculation, diffs, hunk parsing, checkpoints, rollback, candidate adoption, clean fast-forward apply, refusal on dirty target, and non-git repository handling.

## How to verify
```bash
pytest tests/test_workspaces.py -q
# 10 passed in 10.59s

ruff check .
# All checks passed!

mypy devpilot/core devpilot/config.py devpilot/workspace tests
# Success: no issues found in 9 source files
```

## Deviations from spec
- None.

## Contract change requests
- None.

## Known gaps / follow-ups
- None.
