# WP-G08 — Fixture Repositories (FX1–FX5)
**Status:** ready-for-review
**Branch:** wp/g08-fixtures   **Commits:** ac6982d

## What I built
- `fixtures/fx1_feature_discounts`:
  - `shopcart` package with `Cart`, `Item`, and `round_money`.
  - Consistent Google-style docstrings and type annotations.
  - 10 passing visible tests in `tests/test_cart.py`.
  - 8 hidden grading tests in `.hidden/test_hidden_cart.py` covering discount codes (`SAVE10`, `FLAT5`), threshold gates, negative price guards, and convention consistency.
  - `scenario.toml`, clean `README.md`, and `.hidden/NOTES.md`.
- `fixtures/fx2_bug_pagination` (Flagship demo):
  - `pager` package with `paginate` and `Page`.
  - Seeded integer-division defect `page_count = len(items) // per_page`.
  - 6 passing visible tests in `tests/test_pager.py` (exact multiples).
  - 8 hidden tests in `.hidden/test_hidden_pager.py` covering remainder pagination and edge cases (fails on baseline code).
  - `scenario.toml`, `README.md`, and `.hidden/NOTES.md`.
- `fixtures/fx3_red_test_recovery`:
  - `textstats` package with `word_freq` using `str.split(" ")`.
  - Intentionally omits docstrings to represent stylistic variance across repositories.
  - Baseline tests in `tests/test_stats.py` with **exactly 2 failing tests** (`test_multiple_spaces`, `test_newlines`) and 4 passing tests.
  - 5 hidden tests in `.hidden/test_hidden_textstats.py`.
  - `scenario.toml`, `README.md`, and `.hidden/NOTES.md`.
- `fixtures/fx4_security_notes_api`:
  - `notes_api` package backed by SQLite.
  - 3 planted security issues: SQL injection (CWE-89) in `search_notes`, hardcoded secret (CWE-798) in `config.py`, command injection via `shell=True` (CWE-78) in `export_note`.
  - 3 passing visible tests in `tests/test_notes.py`.
  - 3 hidden tests in `.hidden/test_hidden_notes.py` testing the requested `limit` parameter and SQLi payloads.
  - `scenario.toml`, `README.md`, and `.hidden/NOTES.md`.
- `fixtures/fx5_chaos` (3 sub-scenarios):
  - `fx5a_ambiguous`: RepGen module with ambiguous request, `answers.json` selecting "cache results", and performance grading tests.
  - `fx5b_tool_outage`: Statistics module with `chaos = { disable_tools = ["search.rg", "scan.bandit"] }` in `scenario.toml`.
  - `fx5c_contradiction`: Token validator with contradictory test assertions, `answers.json` selecting "accept partial", and `COMPLETED_PARTIAL` expected outcome.
- Secrecy integrity:
  - All planted defects are documented **strictly inside `.hidden/NOTES.md`** and never leaked in visible READMEs or code comments.
- Tests (`tests/test_fixtures.py`):
  - 8 tests verifying directory layout, scenario schemas, secrecy boundaries, baseline passes, exactly 2 red tests on FX3, and hidden test failures on baseline code.

## How to verify
```bash
pytest tests/test_fixtures.py -q
# 8 passed in 13.19s

ruff check .
# All checks passed!

mypy devpilot/core devpilot/config.py tests
# Success: no issues found in 7 source files
```

## Deviations from spec
- Added `.claude` to `extend-exclude` in `pyproject.toml` so ruff linting ignores Claude agent worktree directories.

## Contract change requests
- None.

## Known gaps / follow-ups
- Eval harness running against these fixtures is scheduled for WP-G14.
