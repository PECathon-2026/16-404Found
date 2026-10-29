# WP-G03 — Review (Claude)

**Verdict:** changes requested. The worktree design, the temp-index `tree_sha` and the hunk parser are good (17 tests passing). Fix the items below on branch `wp/g03-workspaces`, with a regression test for each.

## Must fix

### R1 — Never write to the user's repo config 🔴
`create_main` runs `git config user.name/user.email` **on the target repo** (`git_worktrees.py:185-186`), which overwrites the user's repo-local identity. Remove these calls. For commits made by DevPilot (checkpoint, synthetic baseline, adopt), pass identity per command via env: `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` = `DevPilot` / `devpilot@localhost`. Test: the target's `git config --local --get user.name` is unchanged after a full mission lifecycle.

### R2 — `apply_to_target` silently does nothing for non-git targets 🔴
For a synthetic repo, `self.repo` points at `runs/<id>/synthetic_repo`, so the ff-merge lands in DevPilot's copy and the user's folder is unchanged — yet success is returned. Required:
- Keep `self.target = original path` separately from `self.repo`.
- Synthetic case: compute `diff(main, baseline)` file list (added/modified/deleted). Refuse if any of those target files changed since mission start (store sha256 of each original file at copy time). Otherwise copy the files over and delete the deleted ones, then return the main tree sha.
- Test: a non-git target folder actually receives the change.

### R3 — Dirty target: baseline and main start from different states 🟠
With uncommitted user changes, `main` starts from the `git stash create` snapshot, but `baseline` is detached at `HEAD`. Diffs and baseline test runs then attribute the user's uncommitted edits to the agent. Required: store `self.base_ref` and create the baseline worktree from **`base_ref`**.

Applying is also a problem: an ff-merge from a stash commit would put a two-parent "WIP on …" commit into the user's history, and `apply_to_target` refuses dirty targets anyway. Do this instead:
- At mission start, if the target is dirty, create the mission branch from `HEAD` and then **apply the user's uncommitted diff as the first commit** `devpilot: snapshot of uncommitted changes` (`git diff HEAD | git apply` inside the main worktree, or read-tree from the stash tree). Mark it in metadata.
- At apply time, if `dirty_at_start`, refuse ff-merge and instead offer `apply_patch` mode: `git diff <snapshot-commit>..devpilot/<mid>` applied with `git apply --3way` to the user's working tree, after confirming that the working tree still matches the snapshot. Document this in the handoff.

### R4 — Cleanup 🟡
Add `async def cleanup(keep_branch: bool = True)`: `git worktree remove --force` for each worktree, then `git worktree prune`. Without it, worktree registrations accumulate in the user's `.git/worktrees`. Call it from tests.

## Nits
- `fork()` comment says "Snapshot from_ref working tree to commit if uncommitted", but nothing is committed (it copies via read-tree). Fix the comment.
- `parse_diff_hunks`: handle quoted paths (`diff --git "a/sp ace.py" "b/sp ace.py"`) and renames. Add `-c core.quotepath=false` to diff calls.
