# DevPilot

**PECathon 2026 – PS-001**

A multi-agent AI system that turns a plain-English request into a tested, reviewed, human-approved code change in a small local repo.

---

## Architecture

```
User request
     |
 Orchestrator (decides the next step from shared state)
     |
 +---+-----------+------------+-----------+
 |               |            |           |
Planner       Developer     Verifier    Reviewer
(plan, revise) (tools, edit) (tests +    (code review +
                              own checks) security)
     \_______________ Shared State + Message Board ____/
                         |
                  Human Approval -> apply diff to real repo
```

The Orchestrator reads shared state after every agent step and picks the next action. Agents communicate through **typed messages** on a shared message board. The flow is not a fixed pipeline — it adapts to test failures, reviewer findings, and plan gaps.

---

## Agent Roles

| Agent | Job | Tools |
|---|---|---|
| **Planner** | Turns the request into testable criteria and tasks. Asks a clarifying question if the request is too vague. Revises the plan when the Developer finds work that was missed. | `read_file`, `search_code`, `list_files`, `clarify`, `set_plan` |
| **Developer** | Implements the change. Reads existing code first. Never repeats a previous attempt. Responds to test failures, verifier findings, and review issues. Posts `PLAN_GAP` if it discovers unplanned work. | `read_file`, `edit_file`, `search_code`, `list_files`, `run_command`, `git_diff` |
| **Verifier** | Runs the project's test suite. Writes and runs independent check scripts for each criterion (edge cases: empty cart, negative total, zero price). Falls back to `python3 -m unittest` or `py_compile` if `pytest` is unavailable. | `run_command`, `read_file`, `write_check`, `post_finding` |
| **Reviewer** | Reviews the git diff, reads all imported files, scans for secrets, checks style against `AGENTS.md`. Posts `REVIEW_ISSUE` for every problem. Re-evaluates if the Developer sends a `DEV_REPLY`. | `git_diff`, `read_file`, `scan_secrets`, `search_code`, `post_issue` |

---

## Communication and Shared State

### Message types

| Type | From → To | Meaning |
|---|---|---|
| `PLAN_READY` | Planner → all | Criteria and tasks are set |
| `PLAN_REVISED` | Planner → all | Plan updated after a `PLAN_GAP` |
| `CLARIFY` | Planner → Human | Request is unclear |
| `TEST_FAILURE` | Verifier → Developer | Test failed |
| `VERIFY_FINDING` | Verifier → Developer | Criterion not met by own check |
| `REVIEW_ISSUE` | Reviewer → Developer | Code quality or security problem |
| `DEV_REPLY` | Developer → Reviewer | Developer disputes an issue |
| `PLAN_GAP` | Developer → Planner | Missed work discovered |
| `TOOL_UNAVAILABLE` | Orchestrator → Agent | Tool failed, use a fallback |
| `ESCALATE` | Orchestrator → Human | Stuck after max retries |

### Shared state fields

| Field | Type | Description |
|---|---|---|
| `request` | str | Original user request |
| `repo_path` | str | Original repo (read-only until approved) |
| `workspace_path` | str | Temp copy where agents work |
| `criteria[]` | Criterion | Acceptance criteria with status |
| `tasks[]` | Task | Actionable tasks with owner |
| `attempts[]` | Attempt | What was tried (prevents repetition) |
| `messages[]` | Message | Message board contents |
| `test_runs[]` | TestRun | Full history of test executions |
| `review_issues[]` | ReviewIssue | Reviewer findings |
| `retries` | int | Current retry count |
| `status` | RunStatus | planning/building/verifying/reviewing/awaiting_human/done/escalated/stopped |

All state changes are logged to `runs/<run_id>.jsonl` (one JSON line per event).

---

## Setup

```bash
git clone <repo>
cd devpilot
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Requirements

- Python 3.11+
- An Anthropic API key (`claude-opus-4-5` or similar)

---

## Configuration

`.env` variables:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `MODEL` | `claude-opus-4-5` | Model to use for all agents |
| `MAX_RETRIES` | `3` | Max fix attempts before escalation |

---

## Running

### CLI (single mission)

```bash
python3 main.py --repo demo_repos/mini_shop \
  --request "Add coupon support. SAVE10 gives 10% off."
```

With a simulated missing tool:

```bash
python3 main.py --repo demo_repos/notools_repo \
  --request "Add a modulo function." \
  --simulate-missing pytest
```

### Dashboard (Streamlit)

```bash
streamlit run dashboard/app.py
```

### Run all scenarios

```bash
python3 scripts/run_scenarios.py
```

### Baseline vs DevPilot comparison

```bash
python3 scripts/compare.py
```

---

## Tool List

| Tool | Safety Layer | Description |
|---|---|---|
| `read_file` | Path check | Read a file within the workspace |
| `edit_file` | Path check | Write a file within the workspace |
| `search_code` | Path check | Search for a pattern in workspace files |
| `list_files` | Path check | List workspace files |
| `run_command` | Allow/block list + timeout | Run allowed shell commands only |
| `git_diff` | – | Diff between original and workspace |
| `write_check` | Temp dir only | Write a Verifier check script |
| `post_finding` | – | Post TEST_FAILURE or VERIFY_FINDING |
| `scan_secrets` | Path check | Scan for hardcoded secrets and unsafe code |
| `clarify` | – | Post a CLARIFY question to the human |
| `set_plan` | – | Set/revise criteria and tasks |

---

## Execution Boundaries

- Every agent works on a **temp copy** of the repo (`workspace_path`), never the original.
- No file can be read or written outside `workspace_path` during a run.
- The original repo is only modified **after explicit human approval**.

---

## Human Approval

After all criteria are met and the review is clean, DevPilot:
1. Shows the full unified diff.
2. Shows the criteria summary (VERIFIED / NOT VERIFIED).
3. Shows open review issues.
4. Generates `runs/<run_id>_report.md`.
5. Asks for **Approve / Reject** (CLI: `y/N`; dashboard: buttons).

Rejecting leaves the original repo **completely unchanged** (verified with `git diff`).

---

## Security Assumptions

- The safety layer is enforced in code, not just by prompt instructions.
- All file path operations are resolved and checked against `workspace_path`.
- The command allow-list is checked with regex on every `run_command` call.
- `..`, symlink escapes, and absolute paths outside the workspace are all blocked.
- Blocked attempts are logged as `BLOCKED` events and shown on the dashboard.
- API keys are read from `.env`, never committed.

---

## Demo Repos

| Repo | Purpose |
|---|---|
| `mini_shop` | Coupon support, rounding trap, hardcoded key |
| `bugfix_repo` | Off-by-one bug with failing test |
| `failing_test_repo` | Wrong function name in import |
| `security_repo` | SQL injection + hardcoded password |
| `stuck_repo` | Unsolvable in 3 retries → escalation |
| `notools_repo` | pytest simulated missing → fallback |
| `revision_repo` | Plan gap: function used in two places |

---

## Known Limitations

- Agents share a single LLM model (no specialization by model size).
- The `write_check` temp scripts run in a separate directory; they must import from the workspace via sys.path manipulation.
- Dashboard auto-refresh uses `time.sleep` + `st.rerun()`, which is polling-based.
- Very large repos may hit the output size limit (50 000 characters).
- The Reviewer only scans Python files by default.
- Parallel Verifier + Reviewer (mentioned as a bonus) is not implemented; they run sequentially.

---

## Test Results

Run `pytest tests/` to verify all safety and core module tests.

```
tests/test_core.py      - state, logger, message board
tests/test_tools.py     - safety layer, file tools, secret scanner
```

All safety blocking tests prove:
- `../` traversal is blocked
- `rm -rf` is blocked
- `curl` is blocked
- Paths outside the workspace are blocked
- The secret scanner finds `sk_live_FAKE1234567890` in `mini_shop/config.py`
