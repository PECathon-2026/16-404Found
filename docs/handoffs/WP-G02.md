# WP-G02 — Executor, Policy, Tool Gateway (Review Fixes)
**Status:** ready-for-review
**Branch:** wp/g02-gateway-policy

## What I built / Fixed
Addressed all items from `docs/handoffs/WP-G02.review.md` (R1–R8) and follow-up items (a) and (b):

- **R1 (Command arguments jail & forbidden flags)**:
  - `CommandPolicy.classify(argv, caller_role, workspace)` now validates that path arguments resolve strictly inside the workspace. Node IDs like `tests/test_x.py::test_a` are split before resolution.
  - Added denylist of forbidden flags: `--output`, `--no-index`, `--basetemp`, `--rootdir`, `--confcutdir`, `--fix`, `--unsafe-fixes`, `--pyargs`, `--exec-path`, `--git-dir`, `--work-tree`, `--cache-dir`, `-o` and `-c` on git, and `-p` on pytest.
  - Removed `npx jest *` from allowlist.
- **R2 (Evidence bound to workspace tree hash)**:
  - `DefaultToolGateway` now accepts `workspaces: Workspaces | None`.
  - For code-bound tools, `tree_sha` is read before and after execution; if changed, `workspace_changed_during_run` is recorded. If `workspaces` is None, `unbound: True` is flagged in structured output.
- **R3 (API name mapping roundtrip)**:
  - Replaced ad-hoc string replacement with explicit bidirectional mapping (`_api_to_dotted` and `_dotted_to_api`), seeded with all tools from `modes.REGISTRY`. `fs.write_probe` maps reliably to `fs_write_probe` and round-trips.
- **R4 (Dropped `python -c`)**:
  - Removed `python -c *` from `DEFAULT_ALLOW_PATTERNS` and `config/policy.toml`.
- **R5 (Test protection gaps)**:
  - Implemented multiset comparison (`collections.Counter`) to prevent removing duplicated asserts.
  - Implemented reachability analysis: assertions placed after `return`/`raise` or nested in statically `False` branches (`if False:`) are treated as removed.
  - Counted `pytest.raises`, `self.assertRaises`, and `self.assert*` method calls as assertions.
  - Tracked test function definitions; removing or renaming existing `test_*` functions is blocked.
- **R6 (`ask` tier approver callback)**:
  - Added `approver: Callable[[ToolContext, list[str]], Awaitable[bool]] | None` to `DefaultToolGateway`. Without approver, `ask` commands raise `APPROVAL_REQUIRED`; if rejected by approver, `APPROVAL_DENIED` is returned.
- **R7 (Secret redaction in TOOL_CALL arguments)**:
  - Arguments in `TOOL_CALL` events are now sanitized with `redact_secrets`.
- **R8 (Gateway-level defense-in-depth pre-checks)**:
  - `DefaultToolGateway.execute` runs path-jail and command-policy pre-checks on `path`, `paths`, `selector`, `selectors`, `argv`, and `command` before tool execution.
- **Item (a) (FileEvidenceLedger per-mission numbering)**:
  - `FileEvidenceLedger` now sequences IDs (`E-0001`, `E-0002`, ...) per mission across all `workspace_ref` values, and files logs in `runs/<mission_id>/evidence/`.
  - Simplified `MissionEvidenceLedger` in `devpilot/wiring.py` to subclass `FileEvidenceLedger` directly.
- **Item (b) (Unregistered tool event)**:
  - `DefaultToolGateway.execute` emits `EventType.TOOL_UNAVAILABLE` when a tool is not registered.

## How to verify
```bash
python -m pytest -q tests/test_policy.py tests/test_gateway.py tests/test_executor.py
# 44 passed

python -m ruff check .
# All checks passed!
```
