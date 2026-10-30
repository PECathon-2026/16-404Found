# WP-G04 — Read/Write/Search/Git/Shell Tools
**Status:** ready-for-review
**Branch:** wp/g04-tools

## What I built
- `devpilot/tools/registry.py`: Central tool implementations and registration module exposing `register_all(gateway, ctx)` adhering to the contract defined in `docs/handoffs/WP-C10.md`.
- Implemented all tools referenced in `devpilot.engine.modes._MODES` (26 tools total, 52 registered names with API underscore twins):
  - `fs.list`: Directory hierarchy exploration with depth capping (1–4) and ignoring standard development noise (`.git`, `__pycache__`, `node_modules`, `.venv`, etc.).
  - `fs.read`: Line-numbered output, start/end range support, capped at 400 lines per call.
  - `fs.edit`: Exact unique match replacement; provides closest match line hint via `difflib.get_close_matches` on `NOT_FOUND`; handles `AMBIGUOUS_MATCH` when `count > 1`; enforces test assertion protection policy (`TEST_PROTECTION_ASSERTION_MODIFIED`).
  - `fs.write`: Creates new files; refuses overwrite of existing files unless `overwrite=True` and file < 200 lines (`POLICY_DENIED`); enforces test assertion protection.
  - `fs.write_probe`: Writes isolated verification probe scripts to `runs/<mission_id>/probes/<name>`.
  - `search.code`: Ripgrep search with pure-Python `re` walker fallback; guarantees 100% canonical match formatting parity (`path:line: text`).
  - `git.status`: Working tree inspection in porcelain format.
  - `git.diff`: Working tree and staged diff inspection.
  - `git.log`: Recent oneline commit history.
  - `shell.run`: Allowlisted command execution via `LocalExecutor`; validates commands against `CommandPolicy` (allow, ask, deny tiers, shell metacharacter rejection, forbidden flag protection, and workspace path containment).
  - `board.read`: Reads blackboard state, plan, ACs, tasks, or budget slices.
  - `msg.send`: Sends inter-agent and Shogun findings and messages.
  - `memory.recall`: Queries organizational memory with empty list `[]` fallback when unconfigured.
  - `test.run` and `test.rerun`: Delegates to `ctx.test_runner` or returns `TOOL_UNAVAILABLE` when test runner is not configured.
  - `scan.secrets` and `scan.sast`: Initial security scan tools returning structured findings.
  - `search.symbols` and `graph.callers`: Delegates to `ctx.repo_intel` when available or returns `TOOL_UNAVAILABLE`.
  - Stubs: `lab.differential`, `lab.property`, `lab.mutation`, `lab.coverage`, `lab.integrity`, `debug.ddmin`, `scan.taint` returning `TOOL_UNAVAILABLE` with clear packet references.
- Tests in `tests/test_tools.py`:
  - 7 unit test suites testing all operations, error codes (`NOT_FOUND`, `AMBIGUOUS_MATCH`, `INVALID_ARGS`, `POLICY_DENIED`, `TEST_PROTECTION_ASSERTION_MODIFIED`, `TOOL_UNAVAILABLE`), and parity test verifying exact match parity between ripgrep and pure-Python `re` walker.

## How to verify
```bash
python -m pytest -q tests/test_tools.py
# 7 passed in 7.48s

python -m ruff check .
# All checks passed!
```

## Deviations from spec
- None.

## Contract change requests
- None.

## Known gaps / follow-ups
- Stubs for `lab.*`, `debug.ddmin`, `scan.taint` will be replaced by WP-C06, WP-C07.
