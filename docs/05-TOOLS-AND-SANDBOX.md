# 05 — Tools & Execution Boundaries

All tool calls go through `ToolGateway.execute(agent_id, role, tool_use)`:

```
LLM tool_use ──► schema validate ──► role permission check ──► policy check ──► circuit breaker
            ──► execute (timeout, scrubbed env, cwd=workspace) ──► redact ──► truncate
            ──► write Evidence record ──► emit TOOL_CALL event ──► tool_result to LLM
```

## 1. Tool catalogue

| Tool | Purpose | Key args | Side effects | Fallback if unavailable |
|---|---|---|---|---|
| `fs.list` | Directory tree | `path`, `depth≤4` | none | — (pure Python) |
| `fs.read` | Read file (line ranges) | `path`, `start?`, `end?` | none | — |
| `search.code` | Regex/text search | `pattern`, `glob?`, `max_results` | none | `ripgrep` → **pure-Python `re` walker** |
| `fs.edit` | Exact string replace | `path`, `old`, `new`, `count=1` | modifies workspace | — |
| `fs.write` | Create new file | `path`, `content` | creates file (refuses overwrite of existing unless `overwrite=true` and file < 200 lines) | — |
| `fs.write_probe` | Verifier probe file | `name`, `content` | writes to `runs/<id>/probes/` only | — |
| `test.run` | Run test suite / subset | `selector?`, `extra_args?` | runs code | pytest → `python -m unittest` (if detected) |
| `shell.run` | Allowlisted command | `argv: list[str]` | depends | — |
| `git.status` / `git.diff` / `git.log` | Inspect changes | `paths?`, `staged?` | none | — |
| `scan.secrets` | Secret detection | `scope: diff|repo` | none | — (built-in) |
| `scan.static` | SAST | `paths` | none | `bandit` → `semgrep` → **built-in AST rules** |
| `memory.recall` | Query memory | `query`, `k=5` | none | returns `[]` |
| `board.read` | Read blackboard view | `section` | none | — |
| `msg.send` | Message another agent | `to`, `type`, `subject`, `body`, `refs`, `evidence_ids` | enqueues | — |
| `human.ask` | Ask human (Shogun only) | `question`, `options?` | blocks for input | — |

### JSON schema example (as sent to the model)

```json
{
  "name": "fs_edit",
  "description": "Replace an exact, unique string in a file inside the workspace. Read the file first. 'old' must match exactly once unless count is given. Use for all modifications to existing files.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path":  {"type": "string", "description": "Workspace-relative path, e.g. src/cart.py"},
      "old":   {"type": "string"},
      "new":   {"type": "string"},
      "count": {"type": "integer", "minimum": 1, "default": 1},
      "rationale": {"type": "string", "description": "One sentence: why this edit (shown in run log)."}
    },
    "required": ["path", "old", "new", "rationale"]
  }
}
```
> Every tool has a required `rationale` argument → the run log shows **why** each tool was chosen (Tool-Calling Intelligence criterion). (API tool names use `_`; we display them as `fs.edit`.)

### Tool result envelope (returned to the LLM)

```json
{"ok": false,
 "tool": "search.code",
 "evidence_id": "E-0031",
 "error": {"code": "TOOL_UNAVAILABLE", "message": "ripgrep not found on PATH",
           "fallback_used": "python_re_walker"},
 "output": "src/pager.py:41:    pages = total // size\n...",
 "truncated": false}
```
Error codes: `POLICY_DENIED`, `PATH_OUTSIDE_WORKSPACE`, `LOCKED_BY`, `TIMEOUT`, `TOOL_UNAVAILABLE`, `CIRCUIT_OPEN`, `NOT_FOUND`, `AMBIGUOUS_MATCH`, `INVALID_ARGS`, `NONZERO_EXIT`.

---

## 2. Policy: filesystem jail

```python
def resolve_in_workspace(ws: Path, rel: str) -> Path:
    p = (ws / rel).resolve()                        # resolves symlinks and ..
    if not p.is_relative_to(ws.resolve()):
        raise PolicyDenied("PATH_OUTSIDE_WORKSPACE", rel)
    if any(part == ".git" for part in p.relative_to(ws).parts):
        raise PolicyDenied("GIT_INTERNALS", rel)
    return p
```
- **Write-deny globs** (even inside workspace): `.git/**`, `.github/workflows/**`, `**/.env*`, `**/*.pem`, `**/id_rsa*`, lockfiles (`poetry.lock`, `package-lock.json`) unless plan allows.
- **Read-redact globs:** `**/.env*`, `**/*secret*`, `**/*.pem` → content returned with values masked (`API_KEY=****`). The Security Inspector receives a flag that the file exists and has N secret-like values.
- **Test protection:** edits to files matching `tests/**`, `test_*.py`, `*_test.py`, `*.spec.ts` that **modify or delete existing `assert` lines** are denied unless `task.may_edit_tests`. Adding new tests is allowed.
- Size limits: read ≤ 400 lines per call; write ≤ 100 KB.

## 3. Policy: command execution

- `subprocess.run(argv, shell=False, cwd=workspace, env=SCRUBBED_ENV, timeout=tool_timeout_s, stdin=DEVNULL)`.
- `SCRUBBED_ENV` = `{PATH, HOME/USERPROFILE, SYSTEMROOT (win), PYTHONPATH=workspace, LANG}` — **no API keys**, no cloud creds.
- Argument strings containing shell metacharacters (`;`, `&&`, `|`, `` ` ``, `$(`, `>`, `<`) are rejected (we never invoke a shell, so they would be inert anyway — rejection makes intent visible).

### Three-tier allowlist (`config/policy.toml`)

```toml
[commands.allow]          # run without asking
patterns = [
  "python -m pytest *", "pytest *", "python -m unittest *",
  "python -m ruff check *", "ruff check *", "python -m flake8 *", "python -m mypy *",
  "python -m bandit *", "semgrep --config auto *",
  "npm test", "npm run test *", "npm run lint *", "npx jest *",
  "git status *", "git diff *", "git log *", "git show *",
  "python -c *",                 # ONLY when tool caller is Verifier/Sentinel; inspected for imports of os/subprocess/shutil
]

[commands.ask]            # requires human approval at runtime (HUMAN_PROMPT)
patterns = ["pip install *", "python -m pip install *", "npm install *", "npm ci"]

[commands.deny]           # always blocked, logged as POLICY_DENIED
patterns = [
  "rm *", "rmdir *", "del *", "Remove-Item *", "format *", "mkfs*", "dd *",
  "git push *", "git reset --hard*", "git clean *", "git checkout -- *", "git rebase *",
  "git commit *",            # only the orchestrator commits
  "curl *", "wget *", "Invoke-WebRequest *", "ssh *", "scp *",
  "sudo *", "chmod *", "chown *", "shutdown *", "reboot *",
  "powershell *", "cmd *", "bash *", "sh *",
]
```
Matching is on the normalised argv (first token resolved via `shutil.which`, basename compared). Default for anything unmatched: **deny**.

## 4. Network
Agents have **no network tools**. Subprocess network is not technically blocked on a laptop (documented limitation); mitigated by allowlist (no curl/wget/pip without approval). Optional hardening: run under Docker with `--network none` (`devpilot run --sandbox docker`, stretch goal).

## 5. Git worktree lifecycle

```
create:  git -C <repo> worktree add -b devpilot/<mid> runs/<mid>/workspace HEAD
         (non-git repo: copytree → git init → commit "devpilot baseline")
checkpoint (orchestrator only, after each green test run):
         git -C ws add -A && git -C ws commit -m "devpilot: <task> attempt <n> [E-xxxx]"
rollback (orchestrator, on REPLAN that discards an approach):
         git -C ws reset --hard <checkpoint>       # allowed for orchestrator, never for agents
apply (after human approval):
         clean target? → git -C <repo> merge --ff-only devpilot/<mid>
         dirty target? → refuse; show instructions (never stash user's work automatically)
cleanup: git worktree remove (keeps branch for inspection)
```

## 6. Circuit breakers & tool failure handling

```python
class CircuitBreaker:
    threshold = 3          # consecutive failures (TIMEOUT / crash / UNAVAILABLE)
    # CLOSED → OPEN after threshold; OPEN tools return CIRCUIT_OPEN immediately with fallback hint.
```
- `TOOL_UNAVAILABLE` on first call (e.g., `rg` missing, `bandit` not installed) → fallback executed transparently, result marked `fallback_used`, event `TOOL_UNAVAILABLE` logged, Security report lists `scanners_unavailable`.
- Test runner `TIMEOUT` twice → Sentinel triage marks `is_environmental=true` → guard `env_failure`.
- Simulated outages for evaluation: `DEVPILOT_DISABLE_TOOLS=search.rg,scan.bandit` env var or `[chaos]` config section; `DEVPILOT_CHAOS_TEST_TIMEOUT=1` forces a test timeout once.

## 7. Output handling
- Truncation: keep first 60 + last 140 lines of long outputs; full output saved at `runs/<id>/evidence/E-xxxx.log` and referenced in the result.
- Redaction: secret regexes applied to all tool output before it reaches the LLM or the logs.
- Evidence record:

```python
class Evidence(BaseModel):
    id: str                       # "E-0021"
    kind: Literal["tool_output","test_run","probe_run","scan","diff","human_input"]
    tool: str
    agent: str
    argv: list[str] | None
    exit_code: int | None
    started_at: datetime; duration_ms: int
    workspace_sha: str            # git tree hash of workspace at execution time (binds evidence to code state)
    summary: str                  # short machine summary ("11 passed, 1 failed")
    log_path: str
    sha256: str                   # of full raw output
```
`workspace_sha` is what lets the report engine say "this test passed **on the final code**".
