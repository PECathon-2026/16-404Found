# WP-C10 — Wiring, CLI and contract follow-ups
**Status:** ready-for-review
**Branch:** wp/c10-wiring (from wp/all-in-one)

## What I built

**Contract follow-ups**
- `state/projector.py`: `BUDGET_WARNING` is now a stateful event. Optional payload keys `fix_cycles`, `replans`, `tournaments` (ints) and `wall_clock_s` (number) are validated (no bools, no negatives, ints must be integral) and written to `mission.budget` as absolute values; other keys are ignored. Bad values raise `ProjectionError` before anything is persisted.
- `orchestrator/orchestrator.py`: `run()` seeds `_fix_cycles`, `_tournaments` and a wall-clock base from `mission.budget`, so a reload keeps them. The fix-cycle `BUDGET_WARNING` now also carries `tournaments`, `replans` and `wall_clock_s`. The wall-clock limit passed to `asyncio.timeout` is reduced by the time already spent.
- `core/ports.py`: `Hunk` TypedDict; `Workspaces.hunks -> list[Hunk]`.
- `JsonlEventStore(fsync=None)`: `None` reads `DEVPILOT_FSYNC` (default on, `"0"` off). Off still flushes. `tests/conftest.py` sets `DEVPILOT_FSYNC=0`.

**Wiring** (`devpilot/wiring.py`): `MissionStack`, `build_stack`, `missing_components`, `EventBridge`, `probe_components`, `MissionEvidenceLedger`, `UnavailableTestRunner`, `ToolRegistryContext`. Steps follow the packet: store and mission, `GitWorkspaces` main and baseline, blackboard, ledger, gateway wired to the bridge (and `settings.chaos.disable_tools`), discovery of the tool registry / test runner / repo intel / ddmin, cassette-wrapped `AnthropicLLM`, `ContextServices`, `ModeRuntime`, `Orchestrator`. `MissionStack.shutdown()` drains the bridge, then calls `workspaces.cleanup()` if it exists.

**Human channels** (`devpilot/human/`): `ConsoleHumanChannel` and `AnswersFileHumanChannel` as specified. Details: the console channel has an `attach(workspaces, blackboard)` hook (called by `build_stack`) so the apply gate can read ACs and run `workspaces.diff()` for the `d` key. Apply needs the literal word `approve`. If a must-priority AC is not VERIFIED it also needs the mission short id. EOF or Ctrl-C at a gate means reject / abort, never approve. The answers file also accepts per-gate lists (consumed in order, last repeats) and `{"choice", "free_text"}` objects. A gate with no answer takes the safe default (apply -> reject).

**CLI** (`devpilot/cli.py`, `devpilot/cli_view.py`): `run`, `doctor`, `events`, `modes`. The `demo` stub is kept. Live view: header with phase stepper, budget line, plan table, last 15 timeline lines coloured by agent (docs/12 section 9), and the active mode with its model. Markers are ASCII (`[x] [>] [ ]`) so status never depends on colour and nothing breaks on cp1252 consoles. Human gates pause the Live display. Cancelling `execute_mission` (Ctrl-C) cancels the orchestrator task, which finishes the mission ABORTED, and the exit code is 130. Exit codes: 0 verified, 2 partial, 3 failed, 130 aborted, 64 usage (including `--mode single`), 66 bad repo or no events file, 69 required component missing, 78 configuration (no API key / bad answers file).

**Tests:** `tests/wiring/` (build_stack, e2e through real wiring, EventBridge, answers file, console channel) and `tests/cli/` (CliRunner commands, execute_mission with cancel/quiet/live render, view). The e2e uses a real temp git repo (copy of fx2), real store/blackboard/worktrees/gateway/bridge, with a scripted `AgentRuntime` and test runner. It runs the full mission to COMPLETED_VERIFIED including a real ff-merge apply, and checks replay equals live state. A gateway event (`TOOL_UNAVAILABLE` from a chaos-disabled tool) travels through the bridge into the real events file.

## How to verify
```
python -m pytest -q                       # 680 passed
python -m pytest -q tests/wiring tests/cli
ruff check .
python -m mypy devpilot/wiring.py devpilot/human devpilot/core devpilot/config.py
python -m devpilot.cli doctor
python -m devpilot.cli modes
python -m devpilot.cli run --repo fixtures/fx2_bug_pagination "x"     # exit 69 until G04/G05 land
```

## First live run once G04 + G05 land
Prerequisites: `devpilot/tools/registry.py` exposing `register_all(gateway, ctx)`, and `devpilot/testing/runner.py` with a class that has `run` and `rerun_isolated`. Discovery constructs it by matching constructor parameter names against `workspaces, executor, ledger, settings, runs_dir, mission_id, gateway, repo_intel, test_runner` (see "Contract for G04/G05" below).
```
$env:ANTHROPIC_API_KEY = "<your key>"          # PowerShell; use export on bash
python -m devpilot.cli doctor                   # expect tool registry / test runner "ok"
copy-item -Recurse fixtures\fx2_bug_pagination $env:TEMP\fx2   # then git init + commit inside it
python -m devpilot.cli run --repo $env:TEMP\fx2 --profile balanced "Last page of results is missing items"
# scripted gates for evals:  --answers answers.json   ({"apply": "approve"})
# offline replay:            --replay runs\<id>\cassette.jsonl
python -m devpilot.cli events <MISSION_ID> --follow
```
The first run records `runs/<id>/cassette.jsonl`; replay it with `--replay` to avoid spending tokens.

### Contract for G04/G05 (discovery)
- `register_all(gateway: DefaultToolGateway, ctx: ToolRegistryContext)`, sync or async. `ctx` has `mission_id, settings, workspaces, executor, ledger, runs_dir, repo_intel, test_runner`.
- Test runner / repo intel / ddmin: the first class defined in the module (names containing `runner` / `intel` / `debug` preferred) having all Protocol methods; constructed with the subset of the services above whose names match its `__init__` parameters. Required parameters we cannot fill make discovery report it missing (with a log warning).
- Candidate modules are listed in `wiring.COMPONENTS`. Repo intel and ddmin modules are guesses (`devpilot.intel.service|intel|repo_intel`, `devpilot.testing.ddmin|triage.ddmin|triage`); update the table when those packets pick a location.

## Deviations
- Evidence ledger: I did not pass `FileEvidenceLedger(runs/<id>/evidence)` directly. `FileEvidenceLedger` numbers and files evidence by `Evidence.workspace_ref`, so `main` and `baseline` would both mint `E-0001` and collide in `mission.evidence`. `MissionEvidenceLedger` wraps it with root `runs_dir` and the mission id as the key, so logs land in `runs/<id>/evidence/E-NNNN.log` with mission-unique ids while `Evidence.workspace_ref` keeps its real value.
- `devpilot/engine/runtime.py` (`hunk_paths`) and `Orchestrator._targeted_selectors` held the hunk key-guessing, not `validators.py`. I replaced it there with the exact `Hunk` keys. `validators.introduced_flag_matches_diff` consumes `path:Lstart-Lend` strings and needed no change. This also fixes a real bug: the orchestrator read `new_lines` but `GitWorkspaces` emits `new_len`, so every hunk was treated as 1 line long.
- `ModeRuntime` and `Orchestrator` receive `cast(Blackboard, bb)`: `EventSourcedBlackboard.emit` has keyword-only extras where the port says `**kw: Any`, which mypy strict rejects.
- Formatting: I did not run `ruff format` over existing files; only new files are formatted.

## Contract changes made
- `ports.Hunk` and `Workspaces.hunks -> list[Hunk]`.
- `BUDGET_WARNING` payload semantics (absolute counters, see above). Projector rejects malformed values.
- `JsonlEventStore.__init__(fsync=...)`, env `DEVPILOT_FSYNC`.
- New optional duck-typed hook: a `HumanChannel` may implement `attach(workspaces, blackboard)`.

## Known gaps
- Suite time did not improve: 77.8 s before (636 tests) and 77.3 to 78.7 s after (680 tests) on this Windows machine; fsync was not the bottleneck here. `--durations` shows the cost is spread over many tests (fixture baselines 3 to 4 s each, the rest under 3 s).
- `DefaultToolGateway.execute` returns `TOOL_UNAVAILABLE` for an unregistered tool without emitting a `TOOL_UNAVAILABLE` event (only the chaos-disabled path emits). With no registry the UI and timeline will not show unavailable tools. Needs a G02 fix.
- `GitWorkspaces.cleanup` (G03 review R4) does not exist yet; `shutdown()` calls it only when present, so worktree registrations leak in the target repo until then.
- `FileEvidenceLedger` keying by `workspace_ref` is a G02 bug (see Deviations); the wrapper is a workaround.
- No report writer is wired (C09 not built): ABORTED/FAILED missions end without a report file. The CLI prints a summary panel instead.
- No tournament (C08) or memory (C09) is wired; `Orchestrator(tournament=None)`.
- `--mode single` exits 64 until WP-G14. `resume`, `approve`, `reject`, `abort`, `report`, `serve`, `eval` from WP-G13 are not implemented.
- `mypy tests` was already blocked before this packet (duplicate module names `engine_helpers`); not addressed.
- Real Ctrl-C on Windows (signal delivery into the Proactor loop) is covered by a cancellation test of `execute_mission`, not by a signal test.
- With `--allow-missing` and no test runner, the mission fails at its first test run (`ComponentUnavailableError` -> FAILED, exit 3).
