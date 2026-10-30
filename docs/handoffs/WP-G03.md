# WP-G03 — Git Workspaces
**Status:** ready-for-review
**Branch:** wp/g03-workspaces

## What I built
- Addressed all items from `docs/handoffs/WP-G03.review.md` (R1–R4 + nits):
  - **R1 (Repo identity untouched):** Removed `git config user.name/email` from user repositories. DevPilot commits pass identity per command via `DEVPILOT_GIT_ENV` (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`). Target repo's local git config is verified untouched.
  - **R2 (Non-git targets receive changes):** Retained `self.target` distinct from `self.repo`. Stored SHA-256 hash snapshot of original files. `apply_to_target()` detects external changes (refuses if modified), deletes removed files, copies over updated/new files from `main` to `self.target`, and returns the main tree SHA.
  - **R3 (Dirty target baseline alignment):** If target is dirty at mission start, creates mission branch from `HEAD`, commits dirty snapshot as first commit, and sets `self.base_ref` to this snapshot commit. Detaches `baseline` worktree at `self.base_ref` so baseline and main start from the identical state. Fast-forward merge is refused when `dirty_at_start`, protecting history from two-parent stash commits.
  - **R4 (Cleanup):** Implemented `cleanup(keep_branch: bool = True)` which invokes `git worktree remove --force` for each registered worktree, cleans directories, and runs `git worktree prune`.
  - **Nits & Typing:**
    - Corrected `fork()` docstring.
    - Added `-c core.quotepath=false` to git diff commands.
    - Updated `parse_diff_hunks` to support quoted paths and file renames (`rename to <path>`).
    - `hunks()` and `parse_diff_hunks()` strictly return `list[Hunk]` adhering to `ports.Hunk` TypedDict (`id`, `path`, `old_start`, `old_len`, `new_start`, `new_len`, `patch`).
- Regression tests in `tests/test_workspaces.py`:
  - 15 unit tests covering all lifecycle operations, R1, R2, R3, R4, quoted path diffs, and renames.

## How to verify
```bash
pytest tests/test_workspaces.py -q
# 15 passed in 12.36s

python -m pytest -q
# 739 passed in 201.62s

ruff check .
# All checks passed!
```

## Deviations from spec
- When `dirty_at_start` is true, `apply_to_target()` refuses fast-forward merge to prevent uncommitted changes from being squashed/mangled in user's git log. Users or higher-level runners can extract `git diff <snapshot_commit>..devpilot/<mid>` and apply via 3-way patch.

## Contract change requests
- None. `hunks()` strictly conforms to `ports.Hunk` TypedDict.

## Known gaps / follow-ups
- None.
