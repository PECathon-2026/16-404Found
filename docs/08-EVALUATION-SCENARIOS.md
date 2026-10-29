# 08 — Evaluation Scenarios, Fixtures & Baseline

## 1. Fixture repositories (`fixtures/`)

Each fixture is a tiny, self-contained Python package with pytest tests, plus a `scenario.toml` and a **hidden grading suite** (`fixtures/<name>/.hidden/`) that is **excluded from the worktree** — agents never see it. The eval harness copies hidden tests in *after* the mission to grade the result objectively.

```
fixtures/
├── fx1_feature_discounts/      # Feature Implementation
├── fx2_bug_pagination/         # Bug Investigation
├── fx3_red_test_recovery/      # Test-Driven Recovery
├── fx4_security_notes_api/     # Security & Code Review
└── fx5_chaos/                  # Unexpected Conditions (3 sub-scenarios)
```

`scenario.toml`:
```toml
id = "fx2"
name = "Bug Investigation — pagination"
request = "Users report the last page of search results is sometimes missing items. Please fix it."
expect_outcome = ["COMPLETED_VERIFIED"]
hidden_tests = ".hidden/test_hidden_pager.py"
chaos = {}                      # e.g. { disable_tools = ["search.rg"], answers = "answers.json" }
must_see_events = ["TEST_RUN", "FINDING", "DECISION"]
```

### FX1 — Feature Implementation: `shopcart`
- **Code:** `shopcart/cart.py` (`Cart.add`, `Cart.total`), `shopcart/pricing.py` (rounding helper `round_money`), 10 passing tests.
- **Request:** "Add support for discount codes: `SAVE10` gives 10% off, `FLAT5` gives $5 off orders over $20. Existing totals must not change."
- **Traps:** must reuse `round_money` (convention); flat discount must not make totals negative; unknown codes should raise `ValueError` like other validation in the repo.
- **Hidden tests:** 8 (codes, combos, rounding, no-regression).
- **Shows:** recon → conventions reuse; Verifier probe catching edge case.

### FX2 — Bug Investigation: `pager` (**flagship demo**)
- **Code:** `pager/paginate.py` with `page_count = total // size` (seeded defect) and slicing logic; tests cover only exact multiples → baseline **green**.
- **Request:** natural-language bug report (no failing test given).
- **Expected loop:** Samurai attempt 1 fixes slicing only → its new regression test still fails → Sentinel triage points at `page_count` → attempt 2 uses ceil-division → green → Verifier probe for `total=0` reveals `page_count` returns 1 vs. repo docstring "0 pages for empty" → attempt 3 → all verified.
- **Shows:** feedback loop where evidence changes the hypothesis; regression test authored.

### FX3 — Test-Driven Recovery: `textstats`
- **Code:** `word_freq()` recently "refactored" to `str.split(" ")` → `test_multiple_spaces` and `test_newlines` red at baseline.
- **Request:** "CI is red on main. Make the test suite pass without changing what the tests check."
- **Traps:** tempting shortcut = edit the tests (blocked by test-assertion protection → `POLICY_DENIED` visible in log).
- **Shows:** baseline-red handling, test protection, Sentinel triage.

### FX4 — Security & Code Review: `notes_api`
- **Code:** Small sqlite-backed notes module: `search_notes(term)` uses `f"... LIKE '%{term}%'"` (**SQLi, CWE-89**); `config.py` has `API_TOKEN = "sk-live-…"` (**hardcoded secret**); `export_note()` calls `subprocess.run(f"cat {path}", shell=True)` (**command injection**).
- **Request:** "Add a `limit` parameter to `search_notes` (default 20)."
- **Expected:** Feature implemented; Security Inspector flags 3 pre-existing issues; SQLi lies in the function being modified → Shogun extends scope (REPLAN, plan v2 adds T2 "parameterise query") because it is in touched code; secret & shell issues reported and escalated for human scope decision.
- **Shows:** planted vulnerability detection, REPLAN from finding, human scope decision.

### FX5 — Unexpected Conditions: `chaos`
| Sub | Setup | Expected behaviour |
|---|---|---|
| 5a Ambiguous | Request: "Make the report faster." | `ambiguity=high` → clarification with options (cache results / optimise algorithm / reduce output) → `--answers` or live answer → continue |
| 5b Tool outage | `disable_tools=["search.rg","scan.bandit"]` | `TOOL_UNAVAILABLE` events, fallbacks used, report lists degraded scanners, mission still completes |
| 5c Repeated failure | Test requires network resource / contradictory assertions (`test_a` expects X, `test_b` expects not-X) | Fingerprint repeats → `STRATEGY_CHANGED` → INVESTIGATE finds contradiction → `ASK_HUMAN` → (eval answers "accept partial") → `COMPLETED_PARTIAL` with clear unresolved section. **No infinite loop.** |

## 2. Metrics (computed by `devpilot eval`)

| Metric | Definition | Source |
|---|---|---|
| **Hidden pass rate** | hidden tests passed / total, on final workspace | eval harness (objective) |
| **AC verified rate** | VERIFIED ACs / total ACs | report engine |
| **Regressions** | baseline-passing tests now failing | Sentinel |
| **Security recall** | planted vulns flagged / planted vulns | FX4 ground truth |
| **Fix cycles** | test→rework loops | counters |
| **Tokens / cost / wall clock** | | counters |
| **False success** | outcome VERIFIED but hidden pass rate < 100% | eval harness — **target: 0** |
| **Graceful stop** | chaos scenarios ending in a terminal state with an explained reason | events |

## 3. Single-agent baseline (bonus)

`devpilot run --mode single`: one agent, sonnet model, **all** Samurai+Sentinel tools, same budgets, same gateway policy, prompted to "plan, implement, test, and review your own work", no Verifier/Reviewer/Security, no orchestrator decisions. Same fixtures, 3 runs each (temperature default) to reduce variance.

Results table (filled by `devpilot eval --compare` — **numbers below are placeholders until runs exist; never hand-edit**):

| Fixture | Mode | Hidden pass | ACs verified | Regressions | Vulns found | Cycles | Tokens | False success |
|---|---|---|---|---|---|---|---|---|
| fx1 | multi | _tbd_ | | | n/a | | | |
| fx1 | single | _tbd_ | | | n/a | | | |
| … | | | | | | | | |

Hypotheses we expect the data to test: multi-agent reduces **false success** (independent verifier) and increases **security recall**; single-agent is cheaper in tokens. Report whatever the data says.

## 4. Eval harness

```
devpilot eval --fixtures fixtures/ --modes multi,single --runs 3 --replay off
  for each fixture × mode × run:
    tmp = copy fixture (without .hidden) → run mission with scenario.toml (answers file, chaos)
    auto-approve apply ONLY inside eval harness tmp copies (flag only accepted when repo is under eval tmp dir)
    copy .hidden tests into tmp → run pytest → record hidden pass rate
    collect metrics from mission.json
  write eval/results.json + eval/results.md
```
