# WP-G02 — Executor, Policy, Tool Gateway
**Status:** ready-for-review
**Branch:** wp/g02-gateway-policy   **Commits:** 619854b

## What I built
- `devpilot/tools/executor_local.py`: `LocalExecutor` implementing `ports.Executor` protocol using `asyncio.create_subprocess_exec` (never shell), running in a scrubbed environment that strips secrets (`ANTHROPIC_API_KEY`, cloud keys), kills the process tree on timeout via `psutil`, and caps stdout/stderr at 5 MB.
- `devpilot/tools/policy.py`:
  - `resolve_in_workspace`: Filesystem path jail that resolves symlinks, `..`, UNC shares (`\\server\share`), and drive letters, strictly prohibiting workspace escape and `.git` access.
  - Write-deny globs (`.git/**`, `.github/workflows/**`, `**/.env*`, `**/*.pem`, lockfiles unless permitted) and read-redaction checks.
  - Command classifier (`CommandPolicy`): Three tiers (`allow`, `ask`, `deny`), metacharacter rejection (`;`, `&&`, `|`, `` ` ``, `$()`, etc.), first token normalization (stripping `.exe`), and `python -c` restricted to Verifier/Sentinel with forbidden import analysis.
  - AST test protection (`check_test_edit_allowed`): Denies removing or modifying existing `assert` statements and forbids adding `skip`/`xfail` decorators without authorization, while permitting new tests.
  - Secret redaction (`redact_secrets`, `redact_file_content`): Masks AWS keys, Anthropic keys, OpenAI keys, GitHub tokens, private keys, connection strings, and generic assignments.
- `devpilot/tools/ledger.py`: `FileEvidenceLedger` implementing `ports.EvidenceLedger`, recording raw logs to `runs/<id>/evidence/E-XXXX.log` with sequential IDs and SHA256 cryptographic digests.
- `devpilot/tools/gateway.py`: `DefaultToolGateway` implementing `ports.ToolGateway`. Implements the full pipeline: naming mapping (`.` <-> `_`), allowed tools check, chaos/disabled tools check (`DEVPILOT_DISABLE_TOOLS`), circuit breaker (tripping after 3 consecutive failures), schema validation (`jsonschema`) with injected required `rationale`, policy execution, output secret redaction, truncation (60 head + 140 tail), evidence persistence, and event emission.
- Tests (32 tests):
  - `tests/test_policy.py` (17 tests): Path jail (traversal, UNC, drive letters, symlink out, `.git`), write-deny, read-redact, command tiers, metacharacters, `python -c` guard, AST test assertion protection, secret redaction.
  - `tests/test_executor.py` (5 tests): Subprocess execution, exit codes, stderr, scrubbed env, timeout killing, nonexistent binary handling.
  - `tests/test_gateway.py` (10 tests): Tool normalization, schema rationale injection, least-privilege checks, circuit breaker, disabled tools, truncation, evidence integrity, lifecycle events.

## How to verify
```bash
pytest tests/test_policy.py tests/test_executor.py tests/test_gateway.py -q
# 32 passed in 2.30s

ruff check .
# All checks passed!

mypy devpilot/core devpilot/config.py devpilot/tools tests
# Success: no issues found in 14 source files
```

## Deviations from spec
- None.

## Contract change requests
- None.

## Known gaps / follow-ups
- Individual concrete tool implementations (`fs.read`, `fs.edit`, `search.code`, etc.) are scheduled for WP-G04 and will register directly into `DefaultToolGateway`.
