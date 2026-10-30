# DevPilot review — siddharth

Reviewed on 2026-10-30 against the masterplan supplied in this conversation.

- Checkout: `.`
- Branch: `siddharth`, tracking `origin/siddharth`
- Commit: `33080b9021239c0a0e3d87adbf46820329234bd6`
- Fetch and fast-forward pull completed. Working tree remained clean.
- Reviewed the Python agents, shared client, state, board, logger, orchestrator, tools, CLI, dashboard, evaluation scripts, baseline, demo fixtures, tests and documentation.
- Dependencies installed successfully in a temporary virtual environment. All execution took place in a separate review copy or synthetic temporary fixtures. No application source was changed.

**Verdict:** the intended modules are present, but the implementation does not yet satisfy the masterplan's end-to-end completion, safety, feedback, verification or approval requirements. The existing test suite covers mainly state containers and straightforward tool cases; passing it does not demonstrate a working mission.

## Executed validation

Python 3.14.6; pytest 9.2.0; installed the branch's `requirements.txt`.

| Check | Actual result |
|---|---|
| Core/tool suite, `python -m pytest tests/ -q -p no:cacheprovider` | 37 passed, 1 collection warning |
| `mini_shop` suite | 8 passed |
| `bugfix_repo` suite | 2 failed, 1 passed — intended off-by-one bug |
| `failing_test_repo` suite | 1 collection error — intended missing import |
| `security_repo` suite | 2 passed; these tests do not exercise SQL injection |
| `notools_repo` suite, without simulated missing pytest | 3 passed |
| `revision_repo` suite | 2 failed, 2 passed — floating-point equality failures before the requested revision |
| `stuck_repo` suite | 1 failed in this execution; random result was 95 |
| Independent review checks | 14 failed, reproducing the requirements gaps below |
| Streamlit AppTest: initial Start Mission page | Loaded without an application exception |
| Streamlit AppTest: select Live View with default refresh | `RuntimeError: AppTest script run timed out after 5(s)` |

The 14 independent checks are in [test_review_regressions.py](validation-evidence.md#review-regression-source). They exercise real file operations, commands and agent dispatch methods. LLM responses and selected orchestration preconditions are explicitly mocked. They are **not** a live Gemini mission or judge-facing mission evidence.

Reproduce them with:

```bash
<review-venv>/bin/python -m pytest \
  docs/reviews/test_review_regressions.py \
  -q -p no:cacheprovider --tb=short
```

Raw execution results for five fixture suites are saved in [demo_validation.json](validation-evidence.md#prior-demo-validation). No live provider run, successful complete mission, real baseline comparison, or browser approval was verified.

## Findings, ordered by priority

### 1. Critical — command execution escapes the safety layer

[tools/safety.py:101](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/safety.py#L101) approves an allowed string prefix, while [tools/command_tool.py:74](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/command_tool.py#L74) executes the entire string using `shell=True`. Command arguments are not checked against the workspace.

**Reproduced:** `ls ; printf review_shell_marker` executed the second command and returned the marker with exit 0. `cat <synthetic original-repo marker>` also read a file outside the workspace with exit 0. Broad permission for `python` permits arbitrary Python code; subprocess cwd does not confine filesystem access. The child also inherits the backend environment.

**Fix:** parse a strict argv grammar, reject shell syntax and unsupported flags/subcommands, validate file arguments, and execute without a shell. Scrub sensitive environment variables. Running Python and tests still requires an OS-level execution boundary to enforce the promise that generated code cannot modify the original repo before approval.

### 2. High — file isolation and protected-file rules are bypassable

[tools/safety.py:74](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/safety.py#L74) uses string `startswith`, so `/workspace_other/file` is accepted under `/workspace`. The path check does not prohibit `.env` or `.git` files. [tools/file_tools.py:50](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/file_tools.py#L50) reads search results without calling the path check; the scanner likewise reads files directly. The orchestrator copies the entire target repo, including sensitive and Git files.

**Reproduced:** a sibling directory whose name begins with the workspace name was readable; direct `read_file` read a synthetic `.env`; `search_code` followed a symlink to a file outside the workspace.

**Fix:** use path-component containment such as `Path.is_relative_to`, enforce protected paths, validate each enumerated file, and exclude sensitive files and Git internals from the agent-visible import. Route scans and searches through the same policy.

### 3. High — normal missions cannot leave the Developer stage

[agents/planner.py:197](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/planner.py#L197) creates pending tasks. [agents/developer.py:203](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/developer.py#L203) never marks a task in progress or done, and exposes no task-completion tool. [core/orchestrator.py:181](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L181) always routes unfinished tasks back to the Developer before considering verification.

**Reproduced:** after a simulated model response performed a real file edit and reported completion, the task remained pending. A nonempty normal plan therefore repeatedly invokes the Developer and eventually reaches the global step limit without the intended verifier/reviewer feedback loop.

**Fix:** implement validated task-result transitions and route completed implementation work to verification. Do not infer completion from unrestricted prose.

### 4. High — step accounting consumes the whole budget on the first call

[agents/developer.py:219](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/developer.py#L219), [agents/verifier.py:199](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/verifier.py#L199), and the other agents add the maximum iteration allowance rather than actual iterations used. The shared loop returns only text, so actual usage is unavailable to callers.

**Reproduced:** a Developer invocation with one simulated response was charged 15 iterations; the next invocation received a zero-iteration budget (`[15, 0]`). This prevents repair even if task transitions are fixed. Multiple tool calls in one response also are not counted separately.

**Fix:** return actual iteration/tool counts and a structured termination reason from the client loop. Escalate explicitly when the remaining budget is exhausted.

### 5. High — verification has no successful-criterion transition and can conceal failed tests

[agents/verifier.py:158](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/verifier.py#L158) supports setting criteria to failed, but no code path sets them to met with evidence. Furthermore, every command, including `ls`, is appended to `test_runs`. [core/orchestrator.py:109](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L109) considers only the latest command's exit code.

**Reproduced:** a real independent probe exited 0 but its criterion stayed unmet. A genuinely failing pytest invocation followed by `ls` made `_failed_tests()` return false.

**Fix:** maintain distinct suite and criterion-check records. Associate criterion outcomes with real executed evidence, and determine suite success from the required test invocation for the current edit. A successful discovery command must never override a failing suite.

### 6. High — the approval gate does not enforce successful verification

[core/orchestrator.py:253](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L253) requests approval whenever there are no open review issues. `_all_criteria_met()` exists but is never used. On exhausted retries for verifier findings, the code can fall through to approval. [dashboard/app.py:410](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/dashboard/app.py#L410) offers direct Apply without checking mission status, criteria, suite results or open issues.

**Reproduced:** with completed tasks and a mocked green-suite/clean-review precondition, the orchestrator requested approval while a criterion was unmet.

**Fix:** implement one fail-closed gate shared by CLI and dashboard: all criteria met with evidence, current required checks successful, review complete and clean. Bind the decision to the exact candidate content and refuse stale or ineligible approval.

### 7. High — applying a change copies the whole snapshot over the original

[core/orchestrator.py:316](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L316) and [dashboard/app.py:414](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/dashboard/app.py#L414) copy every workspace file, rather than only approved changes. This includes caches and Git internals if present. Files deleted from the workspace are not deleted from the original.

**Reproduced:** an original file changed by the user during the mission was overwritten with old workspace content even though it was unrelated to the approved change.

**Fix:** apply an explicit reviewed change set with additions/modifications/deletions, original-content conflict checks and recoverable apply behavior. Exclude metadata and generated files, and share one implementation between CLI and dashboard.

### 8. High — findings cannot be resolved and historical messages keep causing repairs

[agents/reviewer.py:152](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/reviewer.py#L152) only creates open review issues. Neither agent has a tool to resolve an issue or post a typed `DEV_REPLY`; a prose disagreement does not populate the board. `_review_done()` stays true after the first review, so the documented re-review after a repair does not occur. [core/orchestrator.py:116](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L116) treats any historical `VERIFY_FINDING` as current forever.

**Reproduced:** a historical finding still requested repair after its criterion was manually set to met in the test fixture.

**Fix:** correlate messages and issue status with the current change and criterion. Add evidence-backed resolution and dispute tools, consume or acknowledge messages, and invalidate the old review after edits.

### 9. Medium — clarification discards even a supplied human answer

[agents/planner.py:183](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/planner.py#L183) collects the answer, but [agents/planner.py:244](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/planner.py#L244) stops the loop whenever a clarification question exists. The model never receives a further turn to use that answer and create the plan; the orchestrator stops.

**Reproduced:** supplying a concrete coupon answer still made `PlannerAgent.run()` return false without a plan.

**Fix:** distinguish an unanswered question from an answered question. Resume planning with the answer, and provide a real dashboard clarification input rather than returning `n` for every `input()` call.

### 10. Medium — default dashboard refresh prevents rendering

[dashboard/app.py:224](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/dashboard/app.py#L224) sleeps and reruns before loading logs or rendering the mission panels. The default enabled toggle repeats that behavior indefinitely.

**Reproduced:** switching to Live View in Streamlit AppTest timed out after five seconds. The initial Start Mission page loaded successfully.

**Fix:** render the current data before scheduling another refresh, or use a timed Streamlit fragment. Also replace background-thread writes to Streamlit session state with a supported communication mechanism; store an accessible run handle while the mission runs. Criteria and messages should be reconstructible from persisted logs, as the masterplan requires.

### 11. Medium — scenario and comparison results are not trustworthy yet

[scripts/run_scenarios.py:128](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/scripts/run_scenarios.py#L128) compares `str(state.status)` with bare values. A `str, Enum` member renders as `RunStatus.ESCALATED`, not `escalated`. The harness also auto-rejects approval, making completed pre-approval scenarios stop instead of retaining the expected awaiting-human status.

**Reproduced:** the enum comparison fails in an independent check. Additional static findings: the baseline uses any earlier output containing `passed` to claim success; steps are reported as the configured maximum; baseline safety blocks and secrets are hardcoded to zero; DevPilot's “bugs caught” counts met criteria rather than unique reproduced bugs; comparison covers only three scenarios.

**Fix:** use `.value`, assert actual scenario evidence, preserve the pre-approval outcome separately from a test rejection, and derive both systems' metrics consistently from final executed checks and logged findings. Generate a report on escalation and clarification too.

### 12. Medium — demo fixtures do not establish the requested demonstrations

- `mini_shop` already implements SAVE10, uses Decimal and clamps negative totals. Its negative-total behavior is also tested. Asking to add SAVE10 therefore does not seed the masterplan's rounding/negative-total repair demonstration.
- `stuck_repo` uses `random.randint(1, 100)`: it can pass by chance, and replacing the body with `return 42` satisfies its request and test. It does not prove mandatory escalation after three failed repairs.
- `revision_repo/invoice.py` delegates to `apply_tax`, so changing that function's default propagates automatically. Its AGENTS.md explicitly reveals the second caller. The suite already has float equality failures, and existing assertions expect the old 10% rate. This does not reliably force a newly discovered second edit and plan revision.
- The supplied masterplan's rounding wording says 29.97 after a 10% coupon. For three items at 9.99, 29.97 is the subtotal; 26.97 is a valid discounted result under the fixture's stated policy. Clarify that wording rather than changing the assertion to an incorrect total.

**Fix:** make fixtures deterministic and encode the exact intended failure/revision evidence in scenario assertions. Keep only fake secrets in demo inputs.

### 13. Medium — audit and bounded-failure requirements are incomplete

Several tool branches bypass logging, and the logger records mostly short summaries rather than reproducible full inputs/results. State mutations are not universally logged. Test histories are cleared during repair, losing earlier failures from reports. `PLAN_GAP` is posted without its own log event, while the scenario harness looks for such an event. The orchestrator does not consume `TOOL_UNAVAILABLE` or enforce two consecutive tool failures. Attempts only record `edited <path>`; identical edits are not blocked and results are never updated from pending verification.

**Fix:** centralize dispatch, policy, logging and failure counters; retain immutable execution history; record actual edit fingerprints and evidence; implement typed tool-unavailable handling and repeated-attempt rejection in code.

### 14. Medium — fresh-clone setup documentation still targets Anthropic

[README.md:95](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/README.md#L95) documents an Anthropic key and Claude model, while the implementation and `.env.example` require `GEMINI_API_KEY` and default to `gemini-2.5-flash`. The clone command is a placeholder and omits the actual cloned repository directory. `PLAN.md`, referenced in the project rules, is absent on this branch. The dashboard's default model label is also stale, and `MAX_RETRIES` is displayed but not loaded into shared state from the environment.

**Fix:** publish tested setup commands for the actual repo/subdirectory, document Gemini consistently, restore the authoritative plan, and make displayed configuration match enforced configuration.

## Masterplan readiness

| Phase | Assessment |
|---|---|
| 0 — skeleton | Present; dependencies installed successfully. Authoritative PLAN.md missing. |
| 1 — mini_shop traps | Eight tests pass, but coupon and negative-total behavior are already implemented. |
| 2 — state/logger/board | Basic implementation present and covered; full state/event persistence incomplete. |
| 3 — tools/safety | Basic blocked cases pass; independent escape checks fail. |
| 4 — baseline | Present; final-success and measurement logic need correction. |
| 5 — Developer | Present; task completion, step accounting and repeated-attempt enforcement missing. |
| 6 — Verifier | Present; no passing-criterion transition and failed-suite handling is unsafe. |
| 7 — Reviewer | Present; resolution and typed disagreement loop incomplete. |
| 8 — Planner/Orchestrator | Present; normal task flow, clarification resume and fallback routing incomplete. |
| 9 — approval/apply/report | Present; completion gate and change application need correction. |
| 10 — scenarios | Fixtures/scripts present; deterministic outcomes and evidence assertions incomplete. |
| 11 — dashboard | Present; default Live View fails and approval bypasses the shared gate. |
| 12 — comparison/README/demo | Present; metrics and provider/setup documentation need correction; no live comparison verified. |

## Recommended repair order

1. Fix command/file confinement and protect the original repo.
2. Implement task-result transitions, actual step accounting and positive criterion evidence.
3. Implement one approval gate and one safe apply path.
4. Repair findings, re-review, clarification and tool-unavailable/retry behavior.
5. Fix Live View and live run-state delivery.
6. Make scenarios deterministic, preserve full logs and correct comparison metrics.
7. Update setup documentation and record a genuine complete mission with a feedback loop.

The review did not change or commit any repository files. The only checkout change was switching to the requested up-to-date branch.

The subsequent [known-error catalogue](errors-33080b9.md) includes the newly reproduced tool-loop continuation defect and a 15-check regression suite. The initial 14-check results above describe the earlier review run. Reproducer source and captured execution output are embedded in [validation evidence](validation-evidence.md).
