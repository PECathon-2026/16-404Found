# WP-G02 — Review (Claude)

**Verdict:** changes requested. Good structure and tests (39 passing). The issues below were confirmed by running the code. Fix on branch `wp/g02-gateway-policy` and add a regression test for **every** item.

## Must fix

### R1 — Command arguments bypass the path jail 🔴
`CommandPolicy.classify` checks only the command name, never the arguments. These were all classified `allow`:

| argv | Effect |
|---|---|
| `git diff --output=C:/Users/Public/x` | writes a file anywhere |
| `git log --output=../escape.txt` | writes outside the workspace |
| `git diff --no-index C:/Windows/win.ini NUL` | reads any file |
| `ruff check --fix ../../elsewhere` | edits files outside the workspace |
| `pytest --basetemp=C:/some/dir` | **pytest deletes the basetemp directory** (destructive) |

Required:
1. `classify(argv, caller_role, workspace: Path)` — add the workspace parameter.
2. A denylist of flags (prefix match, including the `--flag=value` and `--flag value` forms): `--output`, `-o` (git), `--no-index`, `--basetemp`, `--rootdir`, `--confcutdir`, `--fix`, `--unsafe-fixes`, `-p` (pytest plugin loading), `--pyargs`, `--exec-path`, `-c` (git config injection, when argv[0] is git), `--git-dir`, `--work-tree`, `--cache-dir`.
3. Every remaining argument that looks like a path (contains `/` or `\`, starts with `.`, or exists relative to the workspace) must pass `resolve_in_workspace`. Pytest node ids (`tests/test_x.py::test_a`) must split on `::` first.
4. Remove `npx jest *` (npx can download packages). Keep `npm test`.

### R2 — Evidence is not bound to code state 🔴
`gateway.py:358` hard-codes `workspace_sha="0" * 40`. The completion rule (docs/06 §6, ADR-006) depends on this value. Required:
- Add the constructor parameter `workspaces: Workspaces | None` (the port from `core/ports.py`).
- For tools whose `evidence_kind` is `test_run`, `probe_run`, `property_run`, `differential_run`, `mutation_run`, `coverage` or `diff`, set `workspace_sha = await workspaces.tree_sha(ctx.workspace_ref)` **before** execution. Code could change during a long run, so compute it again after execution; if the two values differ, put `"workspace_changed_during_run": true` in `structured`.
- For other tools, compute it lazily (same call) — it's cheap on small repos. If `workspaces` is None (unit tests), keep zeros but set `structured["unbound"] = True`.

### R3 — API name mapping breaks `fs.write_probe` 🟠
`_normalize_name` turns `fs_write_probe` into `fs.write.probe`, so the Verifier's probe tool is always denied. Replace the string replace with an explicit bidirectional map built in `register()` (`api_name = dotted.replace(".", "_")`; store `api_to_dotted[api_name] = dotted`). Test: every tool name used in `devpilot/engine/modes.py` round-trips.

### R4 — Drop `python -c` from the allowlist 🟠
The regex filter is bypassable (`__import__('o'+'s').system(...)` passed). This was a spec mistake, not yours: agents can already run arbitrary code by writing a test file, so the filter only gives false confidence. Remove `python -c *` from `DEFAULT_ALLOW_PATTERNS` and `config/policy.toml`, and delete the special-casing code. The real boundary is the sandbox tier (WP-G15).

### R5 — Test-protection gaps 🟠
All three of these were allowed:
- removing one of two identical asserts (sets collapse duplicates) → compare **multisets** (`collections.Counter`);
- moving asserts under `if False:` / after a `return` → also compare the **set of test functions** and, for each existing test function, the ordered list of its top-level-reachable assert dumps (treat asserts nested under constant-false `if` / after `return` / `raise` as removed);
- removing `pytest.raises(...)` / `self.assert*` / `unittest` `assertRaises` checks → count these calls as assertions too.

Also: a test function that is removed or renamed (so it no longer matches `test_*`) counts as a removed assertion.

## Should fix
- **R6** The `ask` tier has no handler. Add an `approver: Callable[[ToolContext, list[str]], Awaitable[bool]] | None` constructor param. Without an approver, `ask` → deny with code `APPROVAL_REQUIRED`.
- **R7** Redact the **args** in the `TOOL_CALL` event payload with `redact_secrets` (applied to JSON-serialized string values). `fs.write` content can contain secrets.
- **R8** Policy checks currently happen inside each tool. Add a gateway-level pre-check for any arg named `path`/`paths`/`selector` (path jail) and `argv` (command policy), so a G04 tool that forgets cannot bypass it. Keep the tool-level checks too (defence in depth).

## Accepting
The circuit-breaker semantics (open for the rest of the mission), the truncation format and the ledger format all look good.
