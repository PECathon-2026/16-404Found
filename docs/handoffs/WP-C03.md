# WP-C03 - AgentRuntime
**Status:** ready-for-review
**Branch:** wp/c03-runtime (merge of wp/c01-eventstore + wp/c02-llm-adapter)

## What I built
- `devpilot/engine/errors.py`: `ModeError` > `ModeFailed`, `ModeRefused`, `StepBudgetExceeded`, `BudgetExceeded` (all carry `mode_id`, `reason`); `HiddenSliceError(AssertionError)`.
- `devpilot/engine/validators.py`: `VALIDATORS` registry with all 20 names referenced in `modes.py` (import-time assertion), `ValidationContext`, helpers `parse_diff_names`, `is_test_file`.
- `devpilot/engine/context.py`: `ContextAssembler.assemble(spec, mission, inv, services) -> AssembledContext`, `ContextServices`, one renderer per `Slice` (`RENDERERS`, import-time assertion), truncation marker, `<untrusted>` fencing, `## Assignment` section.
- `devpilot/engine/runtime.py`: `ModeRuntime` (`ports.AgentRuntime`).
- Tests: `tests/engine/` (`test_runtime.py`, `test_context.py`, `test_validators.py`, `engine_helpers.py`), 64 tests, no network.

## How to verify
```
python -m pytest -q tests/engine   -> 64 passed
python -m pytest -q                -> 213 passed
python -m ruff check .             -> All checks passed
python -m mypy devpilot/engine     -> Success: no issues found in 6 source files
```

## Behaviour notes
- Cache breakpoints: exactly 3 per request (last tool = `submit_*`, mode-prompt system block, stable context block of the first user message). If `stable` is empty (e.g. `shogun.decide`) that marker is omitted (2 total).
- Nudge: on `end_turn` without tool use the runtime appends a *new* user message with `submit_instruction(...)` and sets `tool_choice` to the forced submit tool; it stays forced for the rest of the invocation (changing `tool_choice` mid-conversation would invalidate the cache). Before each call, if `needs_submit_instruction(req, model)` is true and the history does not already end with the instruction, it is appended too (no doubling).
- `max_tokens`: if the truncated turn contained `tool_use` blocks they get error `tool_result`s in the same user message that carries the "cut off" text (API requires every tool_use to be answered).
- Tool batching: consecutive read-only calls run via `asyncio.gather`; side-effecting calls (`fs.edit`, `fs.write`, `fs.write_probe`, `shell.run`, `test.run`, `test.rerun`, `msg.send`) run one at a time; groups are processed in the model's order so a read after a write sees the write. All results go back in one user message in tool_use order.
- When a turn has both ordinary tools and the submit tool, ordinary tools run first, then the submit is validated (so `files_changed_matches_diff` sees the edits).
- `gateway.execute` receives the tool name **as the model sent it** (API-safe, e.g. `fs_edit`). The runtime classifies tools with `fs_edit -> fs.edit` (first underscore -> dot). The fence label is `tool:<dotted name>`.
- Fencing: every tool result except `fs.edit`/`fs.write`/`fs.write_probe`/`msg.send` is wrapped in `<untrusted source="tool:...">` (test and shell output are repo-derived too).
- Repair rounds: each rejected submit counts one; more than `max_repair_rounds` rejections -> `MODE_FAILED` + `ModeFailed`.
- Budget: before each call `mission.budget.ratio() >= 1.0` emits `BUDGET_EXCEEDED` then `MODE_FAILED` and raises `BudgetExceeded`. Wall clock uses `asyncio.timeout(spec.limits.wall_clock_s)`; on expiry `MODE_FAILED` + `ModeFailed`.
- Escalation: `MODEL_ESCALATED` is emitted before `MODE_STARTED` (so MODE_STARTED already shows the final model). `tier_override` wins (no escalation event, spec thinking budget).
- Events use `actor=inv.agent_id`, `mode_id=spec.id`, `task_key=inv.task_key`. The `SUBMISSION` payload is `{"submission": Submission}` (what the projector expects). `LLM_TURN` payload has the `usage` the projector charges to the budget.
- Debug mode keeps a deep copy of the last sent history and calls `assert_append_only` before each request. Requests get a shallow copy of the message list so fakes that retain requests see the history as sent.
- Validation hooks: `validation_hooks` keys `diff_names`, `collect_tests`, `hunk_paths`, `path_exists` (async) and `evidence_exists` (sync ledger lookup) override the defaults derived from `services.workspaces` (`diff` parsed for names; `hunks()` entries read with tolerant keys `path|file`, `new_start|start|line_start`, `new_lines|lines|line_end`; `path()` + `Path.exists`). `tests_collect` has no default (skipped unless a hook is given).
- Extra constructor kwarg `spec_lookup` (default `modes.get`) exists for tests.

## Deviations
- `ValidationContext` has two fields beyond the brief: `ledger_exists` (the ledger port as a sync callable) and `path_exists` (needed by `paths_exist`/`plan_paths_plausible`).
- `acceptance_files_are_tests_only` also checks the suite's own `tests[].path` values even without a workspace.
- `Slice.PLAN_HISTORY`, `FINDINGS_OPEN`, etc. renderers were not specified in the brief; I implemented them compactly.
- `invoke` is annotated `-> LLMOutput` (narrower than the port's `BaseModel`).

## Contract change requests
- `ports.ToolGateway.execute`: document whether `name` is the API-safe or dotted name (runtime passes API-safe as received from the model).
- `ports.Workspaces.hunks` returns `list[dict[str, Any]]` with undefined keys; please fix a schema (`path`, `new_start`, `new_lines`) so `introduced_flag_matches_diff` need not guess.
- `ports.ModeInvocation` could carry `repo_key` or the orchestrator can put it in `ContextServices` (current design).
- `ports.RepoIntelService.callers_of` is sync; fine, but `DIFF_CALLERS` has to infer changed symbols from `RepoIntel.repo_map` (top-k only). A `symbols_in_diff()` would be better.
- `ModeInvocation` has no way to pass an explicit recipient for `ContextSlice.TRIAGE` task scoping; the latest TriageReport mission-wide is used.

## Known gaps
- No client-side compaction/context editing (per docs/llm-notes.md, left to API betas); `FAST`-tier summarisation not implemented.
- `devpilot.prompts` (C04) is imported lazily; end-to-end with real prompts is untested here.
- `AGENT_TEXT_DELTA` batching is time-based (50 ms) and flushes at stream end; very slow streams emit one event per delta.
- `MEMORY_RECALLED` events are not emitted by the assembler (renderers have no blackboard handle); C05 can emit them from `AssembledContext.included`.
- Validators that need services (`tests_collect`, `introduced_flag_matches_diff` with real hunks) are only tested with fakes.

## Integration notes for C05 (orchestrator)
- Build one `ModeRuntime(blackboard, llm, gateway, ContextServices(workspaces=..., repo_intel=..., memory=..., repo_key=...), settings)` per mission; `invoke` is safe to call concurrently (all state is per-invocation).
- Pass the dossier as `inv.extra_context["dossier"]` (`DecisionDossier` or dict) for `shogun.decide`; `candidate_scores` (list of `CandidateScore`) for `judge.select`; `event_digest`, `lens`, `strategy_hint`, `question` as described.
- Set `inv.attempt` (1-based) for rework/escalation and `inv.workspace_ref` (`main`, `cand-A`, ...) so diffs and validators look at the right worktree.
- The runtime records `SUBMISSION` and `MODE_FINISHED` itself. It does not emit `TASK_STATE_CHANGED`, `FINDING`, `DECISION` etc.: the orchestrator reacts to the returned model (and writes a `DECISION` event for `shogun.decide`).
- Catch `ModeError` subclasses: `ModeRefused` (Opus fallback already tried server-side), `ModeFailed` (repair/nudge/wall clock), `StepBudgetExceeded`, `BudgetExceeded`; `MODE_FAILED` is already emitted for each.
- Tests can inject `prompt_source`/`constitution` stubs; production defaults import `devpilot.prompts.load_mode_prompt(mode_id)` / `load_constitution()`.
