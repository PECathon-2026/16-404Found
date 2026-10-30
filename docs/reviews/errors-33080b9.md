# DevPilot — all known errors in cached siddharth

Commit: `33080b9021239c0a0e3d87adbf46820329234bd6`. Reviewed against the supplied masterplan.

**40 findings: 1 critical, 19 high, 20 medium.**
The independent regression suite now has **15 failing checks**: the original 14 plus a new tool-loop termination check. Model responses are explicitly mocked; filesystem/command checks use real operations on synthetic temporary fixtures. These are review checks, not a live AI mission.

Scope is the locally cached backend. `imp1` and `wp/g08-fixtures` remain unavailable because remote fetch/clone failed during DNS lookup. No findings are attributed to unseen code.

**Execution evidence**

| Check | Actual result | Captured output |
| --- | --- | --- |
| Core/tool suite | 37 passed; 1 collection warning | [Output](validation-evidence.md#core-tests) |
| Independent regression suite | 15 failed | [Full traces](validation-evidence.md#regression-failures), [JUnit XML](validation-evidence.md#regression-failures) |
| Mini-shop suite | 8 passed | [Output](validation-evidence.md#mini-shop-tests) |
| Revision fixture suite | 2 failed, 2 passed | [Output](validation-evidence.md#revision-fixture-tests) |
| Dashboard AppTest | Start: 0 exceptions; Live View: timeout after 5 seconds | [Output](validation-evidence.md#dashboard-check) |

Exact commands, timestamps, exit codes, stdout, and stderr are in [validation.json](validation-evidence.md). Earlier fixture output is preserved separately in [prior-demo-validation.json](validation-evidence.md#prior-demo-validation).

The core suite warning is `PytestCollectionWarning: cannot collect test class RunTestRecord because it has a __init__ constructor`. It is a collection warning, not an application failure.

**Defect catalogue**

**E01 · Critical · Shell command chaining bypasses the allow-list**

Source: [devpilot/tools/command_tool.py:76](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/command_tool.py#L76). Evidence: Reproduced.

An allowed prefix is executed with shell=True. The synthetic command ls ; printf review_shell_marker runs its second command and exits zero.

Suggested fix: Parse and validate an exact argv grammar; reject shell syntax and execute with shell=False.

Reproducer: `test_command_rejects_shell_separator` in [the review suite](validation-evidence.md#review-regression-source).

**E02 · High · Commands can read files outside the workspace**

Source: [devpilot/tools/safety.py:104](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/safety.py#L104). Evidence: Reproduced.

The command validator checks prefixes, not file arguments. A cat command read a synthetic original-repository marker outside the workspace.

Suggested fix: Validate every path argument against the permitted roots and protected-path policy.

Reproducer: `test_command_rejects_outside_file_argument` in [the review suite](validation-evidence.md#review-regression-source).

**E03 · High · Python execution is not isolated from the original repository**

Source: [devpilot/tools/command_tool.py:74](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/command_tool.py#L74). Evidence: Code review.

A subprocess working directory does not restrict filesystem or process access. Allowed Python and tests run under the host account and inherit its environment.

Suggested fix: Use an enforced execution sandbox with a read-only original repository, writable workspace, resource limits, and a scrubbed environment.

**E04 · High · Workspace containment uses a string prefix**

Source: [devpilot/tools/safety.py:74](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/safety.py#L74). Evidence: Reproduced.

A sibling directory named workspace_other is accepted under workspace because startswith compares strings rather than path components.

Suggested fix: Resolve paths and enforce Path.is_relative_to(workspace), with checks before each file operation.

Reproducer: `test_workspace_prefix_sibling_is_rejected` in [the review suite](validation-evidence.md#review-regression-source).

**E05 · High · Protected .env and .git paths are not denied**

Source: [devpilot/tools/safety.py:59](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/safety.py#L59). Evidence: Reproduced + code review.

A synthetic .env was readable through read_file. The path policy also contains no denial for Git internals.

Suggested fix: Reject protected path components consistently in reads, writes, searches, listings, scans, imports, and apply.

Reproducer: `test_file_tool_denies_dotenv` in [the review suite](validation-evidence.md#review-regression-source).

**E06 · High · Search follows a file symlink outside the workspace**

Source: [devpilot/tools/file_tools.py:55](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/file_tools.py#L55). Evidence: Reproduced.

search_code directly reads enumerated files. A symlink to a synthetic original-repository Python file returned its outside content.

Suggested fix: Run every enumerated file through the containment and protected-path checks before reading.

Reproducer: `test_search_rejects_symlink_to_outside` in [the review suite](validation-evidence.md#review-regression-source).

**E07 · High · Secret scanning bypasses centralized file safety**

Source: [devpilot/tools/secret_scan.py:45](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/tools/secret_scan.py#L45). Evidence: Code review.

scan_file reads paths directly. Reviewer scan-path containment also uses startswith, and scan traversal has no per-file safety check.

Suggested fix: Route scanner reads through the same checked file API; reject escaping symlinks and protected paths.

**E08 · High · Workspace import includes sensitive files and Git metadata**

Source: [devpilot/core/orchestrator.py:44](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L44). Evidence: Code review.

copytree imports the entire target directory without exclusions. Real .env files, .git internals, caches, and other unintended files can become agent-visible.

Suggested fix: Create an explicit import policy that excludes credentials, Git internals, generated artifacts, and escaping symlinks.

**E09 · High · Developer completion never marks tasks done**

Source: [devpilot/agents/developer.py:203](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/developer.py#L203). Evidence: Reproduced.

A mocked model made a real edit and reported completion, but the task remained pending. Unfinished tasks route back to Developer indefinitely.

Suggested fix: Expose validated task completion/results and transition implementation work to verification.

Reproducer: `test_developer_finishing_updates_task` in [the review suite](validation-evidence.md#review-regression-source).

**E10 · High · Agent step counters charge the configured budget**

Source: [devpilot/agents/developer.py:219](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/developer.py#L219). Evidence: Reproduced.

One short invocation consumed fifteen charged steps; the next invocation received zero. Planner, Verifier, and Reviewer use the same accounting pattern.

Suggested fix: Return actual round-trip/tool counts and a termination reason from the shared loop; debit actual usage.

Reproducer: `test_developer_retains_budget_after_short_run` in [the review suite](validation-evidence.md#review-regression-source).

**E11 · High · Tool-use loop stops before using a tool result**

Source: [devpilot/core/gemini_client.py:167](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/gemini_client.py#L167). Evidence: Reproduced with mocked SDK responses.

A valid-shaped function-call response with FinishReason.STOP executes its tool and then breaks. The fixture expected a second model call to consume the tool result; only one occurred and final text was empty.

Suggested fix: Continue after tool calls despite the normal response STOP reason. Finish on a response without tool calls, an external stop condition, or an exhausted budget.

Reproducer: `test_tool_result_is_sent_back_after_stop_function_call` in [the review suite](validation-evidence.md#review-regression-source).

**E12 · High · Verifier cannot mark a successful criterion met**

Source: [devpilot/agents/verifier.py:158](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/verifier.py#L158). Evidence: Reproduced.

The dispatch interface has a failure transition but no passing-evidence transition. A real arithmetic probe exited zero while its criterion stayed unmet.

Suggested fix: Add structured criterion outcomes linked to executed check evidence and the current candidate revision.

Reproducer: `test_verifier_can_mark_passing_criterion` in [the review suite](validation-evidence.md#review-regression-source).

**E13 · High · A successful discovery command hides failed tests**

Source: [devpilot/core/orchestrator.py:109](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L109). Evidence: Reproduced.

Verifier appends every command to test_runs, and the orchestrator checks only the latest exit code. Failing pytest followed by ls was treated as no failed suite.

Suggested fix: Separate discovery, required test suites, and criterion checks; evaluate the required results for the current edit.

Reproducer: `test_failing_suite_is_not_hidden_by_later_ls` in [the review suite](validation-evidence.md#review-regression-source).

**E14 · High · CLI approval does not require verified criteria**

Source: [devpilot/core/orchestrator.py:253](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L253). Evidence: Reproduced.

The final gate only checks for open review issues. With a mocked green-suite/clean-review precondition, approval was requested for an unmet criterion. The all-criteria helper is unused.

Suggested fix: Use one gate requiring completed tasks, passing criterion evidence, current tests, current clean review, and an exact candidate identity.

Reproducer: `test_approval_rejects_unmet_criterion` in [the review suite](validation-evidence.md#review-regression-source).

**E15 · High · Dashboard applies changes without the shared gate**

Source: [devpilot/dashboard/app.py:410](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/dashboard/app.py#L410). Evidence: Code review.

Approve & Apply directly copies files without enforcing eligible status, successful tests, met criteria, current review, or candidate identity.

Suggested fix: Use the same backend gate and apply implementation as the CLI; reject stale and ineligible decisions.

**E16 · High · Apply overwrites unrelated original-repository edits**

Source: [devpilot/core/orchestrator.py:316](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L316). Evidence: Reproduced.

Apply copies every workspace file. An unrelated file edited in the synthetic original during the mission was overwritten with stale workspace content.

Suggested fix: Apply only the reviewed additions/modifications/deletions, check original-content conflicts, and provide recoverable application.

Reproducer: `test_apply_preserves_unmodified_original_files` in [the review suite](validation-evidence.md#review-regression-source).

**E17 · High · Approved deletions are not applied**

Source: [devpilot/core/orchestrator.py:320](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L320). Evidence: Code review.

Apply only iterates existing workspace files. A file deleted from the workspace remains in the original; metadata and generated files are also not excluded.

Suggested fix: Build an explicit change set that includes deletions and excludes metadata, with conflict checks.

**E18 · High · Review issues cannot be resolved or disputed through typed tools**

Source: [devpilot/agents/reviewer.py:152](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/reviewer.py#L152). Evidence: Code review.

Reviewer creates open issues but exposes no resolution transition. Developer has no typed DEV_REPLY posting tool, although Reviewer expects those messages.

Suggested fix: Add evidence-backed issue resolution and typed replies; record accepted and unresolved disputes in shared state.

**E19 · High · Edits do not invalidate the previous review**

Source: [devpilot/core/orchestrator.py:98](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L98). Evidence: Code review.

Any earlier Reviewer completion makes review_done true. Repair branches do not reset review validity, so changed code can retain an old review.

Suggested fix: Bind review to the candidate revision and require re-review after an edit.

**E20 · High · Historical verifier findings keep forcing repair**

Source: [devpilot/core/orchestrator.py:116](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L116). Evidence: Reproduced.

Any VERIFY_FINDING on the board is treated as current. A historical finding still requested repair after its criterion was marked met.

Suggested fix: Track finding lifecycle and candidate/criterion identity; acknowledge or resolve findings after new evidence.

Reproducer: `test_old_finding_does_not_force_repair_after_success` in [the review suite](validation-evidence.md#review-regression-source).

**E21 · Medium · Clarification stops planning after receiving an answer**

Source: [devpilot/agents/planner.py:244](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/planner.py#L244). Evidence: Reproduced.

The planner collects a human answer, but its stop condition remains true whenever a clarification question exists. The answer never produces a follow-up plan.

Suggested fix: Distinguish unanswered and answered questions and resume the model loop with the answer.

Reproducer: `test_planner_uses_clarification_answer_to_continue` in [the review suite](validation-evidence.md#review-regression-source).

**E22 · Medium · Default Live View reruns before rendering mission data**

Source: [devpilot/dashboard/app.py:224](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/dashboard/app.py#L224). Evidence: Reproduced with Streamlit AppTest.

The enabled refresh sleeps then reruns before loading mission panels. The Start page loads, but selecting Live View times out after five seconds.

Suggested fix: Render data before scheduling refresh, or use a supported timed Streamlit fragment.

**E23 · Medium · Background mission thread writes Streamlit session state**

Source: [devpilot/dashboard/app.py:196](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/dashboard/app.py#L196). Evidence: Code review.

The worker thread writes session state without a supported session context. The orchestrator handle is stored only after completion, and terminal input is patched to n.

Suggested fix: Use a supported worker queue/state store, publish a run handle at launch, and implement dashboard clarification/approval state transitions.

**E24 · Medium · Scenario outcome compares enum formatting with plain values**

Source: [devpilot/scripts/run_scenarios.py:128](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/scripts/run_scenarios.py#L128). Evidence: Reproduced.

str(RunStatus.ESCALATED) produces RunStatus.ESCALATED, so comparison with escalated fails.

Suggested fix: Compare enum values or members consistently and serialize status.value.

Reproducer: `test_scenario_outcome_uses_enum_value` in [the review suite](validation-evidence.md#review-regression-source).

**E25 · Medium · Scenario harness rejects approval before checking expected status**

Source: [devpilot/scripts/run_scenarios.py:104](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/scripts/run_scenarios.py#L104). Evidence: Code review.

The harness expects awaiting_human but patches every terminal answer to n, moving approval-ready missions to stopped before evaluating their final state.

Suggested fix: Measure the pre-decision outcome separately, then test rejection and approval in separate isolated cases.

**E26 · Medium · Baseline success depends on any historical passing output**

Source: [devpilot/baseline/single_agent.py:150](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/baseline/single_agent.py#L150). Evidence: Code review.

An earlier output containing passed can mark the baseline successful even when the latest candidate/check fails. Results are not tied to the final candidate.

Suggested fix: Determine success from actual required final checks and acceptance criteria for the final candidate.

**E27 · Medium · Comparison metrics are constants or proxies rather than measured results**

Source: [devpilot/scripts/compare.py:54](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/scripts/compare.py#L54). Evidence: Code review.

Baseline safety blocks and secrets are fixed at zero; steps equal the configured maximum. DevPilot bugs caught counts met criteria, and secret counts depend on issue wording.

Suggested fix: Measure actual steps, safety events, and distinct reproduced/resolved findings consistently for both systems.

**E28 · Medium · Comparison omits required scenarios**

Source: [devpilot/scripts/compare.py:21](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/scripts/compare.py#L21). Evidence: Code review.

The comparison script covers only three scenarios rather than the complete planned evaluation set.

Suggested fix: Run both systems on the defined scenarios and report unsupported outcomes explicitly.

**E29 · Medium · Repair clears test history and can lose reduced-coverage evidence**

Source: [devpilot/core/orchestrator.py:210](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L210). Evidence: Code review.

Several repair branches clear test_runs. Earlier failures and missing-tool exit 127 disappear, while reporting derives reduced coverage only from remaining test records.

Suggested fix: Keep immutable test history, track current verification separately, and persist fallback/reduced-coverage state.

**E30 · Medium · Tool calls and state transitions are not fully auditable**

Source: [devpilot/core/logger.py:27](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/logger.py#L27). Evidence: Code review.

Logging is inconsistent across dispatch branches; many outputs are short summaries. State changes and some blocked/error outcomes are not persisted, so dashboard state is not reconstructible solely from logs.

Suggested fix: Centralize audited dispatch and record structured inputs, bounded results, state transitions, and all denial/error events.

**E31 · Medium · Repeated tool failures and TOOL_UNAVAILABLE routing are incomplete**

Source: [devpilot/core/orchestrator.py:169](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L169). Evidence: Code review.

Verifier posts a tool-unavailable message, but orchestration has no handling branch or consecutive-failure counter to enforce fallback after two failures.

Suggested fix: Track per-agent/tool consecutive failures and route typed fallback instructions or escalation with retained evidence.

**E32 · Medium · Repeated edits are recorded but not blocked**

Source: [devpilot/agents/developer.py:153](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/developer.py#L153). Evidence: Code review.

Attempts record only edited <path> with pending verification. There is no edit fingerprint, enforced duplicate rejection, or final result update.

Suggested fix: Fingerprint attempted changes/approaches, attach outcomes, and enforce duplicate-attempt rejection in code.

**E33 · Medium · PLAN_GAP is posted without the event the harness checks**

Source: [devpilot/agents/developer.py:222](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/agents/developer.py#L222). Evidence: Code review.

Developer posts PLAN_GAP to the board, but logs completion rather than a PLAN_GAP event. The scenario harness searches JSONL event_type for PLAN_GAP.

Suggested fix: Persist the typed message/event when posting it and assert the revised task lifecycle from actual evidence.

**E34 · Medium · Mini-shop already implements the requested coupon and boundary fix**

Source: [devpilot/demo_repos/mini_shop/pricing.py:1](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/demo_repos/mini_shop/pricing.py#L1). Evidence: Code review / fixture design.

SAVE10, Decimal math, and a nonnegative clamp are already present, and negative totals are tested. The request does not reliably produce the planned failure-and-repair demonstration.

Suggested fix: Seed the intended regression deterministically and keep the verifier edge case independent of the ordinary suite.

**E35 · Medium · Stuck fixture does not establish retry-limit escalation**

Source: [devpilot/demo_repos/stuck_repo/solver.py:1](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/demo_repos/stuck_repo/solver.py#L1). Evidence: Prior execution + fixture design.

The fixture uses random.randint and can pass by chance; returning 42 also satisfies it. A previous real run failed with result 95, which is not proof that three repairs must fail.

Suggested fix: Use deterministic constraints and assert exactly three failed repairs followed by evidence-bearing escalation.

**E36 · Medium · Revision fixture is broken and does not force a second edit**

Source: [devpilot/demo_repos/revision_repo/pricing.py:4](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/demo_repos/revision_repo/pricing.py#L4). Evidence: Reproduced fixture failures + code review.

Its initial suite has two floating-point equality failures. The invoice wrapper delegates to apply_tax, so changing the default propagates automatically; repository rules already reveal the second caller.

Suggested fix: Use stable numerical assertions and seed a genuinely separate second change that triggers PLAN_GAP, PLAN_REVISED, and completion.

**E37 · Medium · Setup documentation and authoritative plan are inconsistent**

Source: [devpilot/README.md:95](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/README.md#L95). Evidence: Code review.

README and dashboard defaults describe Anthropic/Claude, but implementation and .env.example use Gemini. Clone instructions are placeholders, and the referenced PLAN.md is absent on this branch.

Suggested fix: Restore the authoritative plan and publish tested fresh-clone instructions/configuration for the actual provider.

**E38 · Medium · Displayed MAX_RETRIES is not loaded into enforced state**

Source: [devpilot/core/state.py:121](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/state.py#L121). Evidence: Code review.

SharedState uses the default retry limit of three; orchestrator construction does not read MAX_RETRIES even though the dashboard displays the environment value.

Suggested fix: Parse and validate configuration once, pass it into state, and display the same enforced values.

**E39 · Medium · Clarification and escalation paths do not generate the required report**

Source: [devpilot/core/orchestrator.py:120](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/core/orchestrator.py#L120). Evidence: Code review.

Report generation is called from human approval rather than all terminal/paused outcomes. Early clarification return and escalation can leave no report with evidence and limitations.

Suggested fix: Persist reports for clarification, escalation, stop, rejection, and completion using retained run evidence.

**E40 · Medium · Dashboard silently returns a partial log after malformed JSON**

Source: [devpilot/dashboard/app.py:96](https://github.com/PECathon-2026/16-404Found/blob/33080b9021239c0a0e3d87adbf46820329234bd6/devpilot/dashboard/app.py#L96). Evidence: Code review.

One broad exception covers the whole log-reading loop and is discarded. A malformed or partially written line stops processing later events without notifying the user.

Suggested fix: Handle an incomplete trailing line separately, preserve subsequent valid events where appropriate, and surface parse failures.

**Demo fixture failures are separate from product defects.**

`bugfix_repo` intentionally returns four items when three are requested (two tests fail). `failing_test_repo` intentionally imports missing say_hello (collection fails). `stuck_repo` previously returned 95 instead of 42. Their exact prior output is retained above. Those seeded failures are expected inputs for the agents; the defects are inability to repair/verify them reliably and fixture designs that fail to prove the intended scenario.

The planted fake payment key and hardcoded demo password are expected scanner inputs. No real credential is asserted to have leaked in this review. The shopping-cart masterplan wording also needs correction: three items at 9.99 subtotal 29.97; after 10% off the stated rounding policy yields 26.97.

**Frontend status, recorded separately.**

The uncommitted frontend is separate from this backend commit. Its most recent recorded build and 28 contract tests passed. An earlier browser run passed six of seven checks and failed keyboard focus restoration; that implementation was subsequently changed, but its browser recheck was blocked by unavailable browser access. This is pending verification, not a confirmed current frontend defect. The live frontend endpoints remain a documented contract awaiting the updated backend.

**Repository access error.**

`Could not resolve host: github.com` blocked remote fetch and clone before authentication. It is an execution-environment network/DNS failure, not a reproduced defect in DevPilot or evidence about the unavailable branches.

**Repair order:** command/file isolation; task completion and actual step accounting; tool-loop continuation; positive verification evidence; shared approval and safe apply; issue resolution and re-review; dashboard lifecycle; retained logs/configuration and deterministic evaluation.

No application source was edited or merged while producing this catalogue. The published review documents live under docs/reviews; execution evidence is embedded in validation-evidence.md.
