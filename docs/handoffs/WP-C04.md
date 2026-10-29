# WP-C04 — Prompts

## What I built
- `devpilot/prompts/constitution.md` (50 lines): identity, evidence over claims, untrusted fences, scope, minimal changes, tool etiquette, tool errors, finishing, communication. No dates, ids or placeholders (cache-stable), and no dotted tool names.
- `devpilot/prompts/modes/<mode_id>.md`: 18 files, one per `REGISTRY` entry, 56-93 lines each, with the six required sections. The "Tools for this mode" section was generated from each `ModeSpec.tools`, so it matches the registry exactly. Each ends with one JSON example that validates against the mode's output model.
- `devpilot/prompts/__init__.py`: `PROMPTS_DIR`, `MODES_DIR`, `load_constitution()`, `load_mode_prompt(mode_id)` (both `functools.cache`; `KeyError` for unknown ids and path-like ids).
- `tests/prompts/test_prompts.py`: registry coverage and no extras, submit tool named, exact tool set (with lookarounds so `fs.write` does not match `fs.write_probe`), JSON example validation, constitution stability, withheld-reasoning statements, section and length checks, no shouting keywords.

## How to verify
`python -m pytest -q tests/prompts` (80 tests), `python -m pytest -q` (87 passed), `python -m ruff check devpilot/prompts tests/prompts`.

## Deviations
- `pyproject.toml` not changed: `[tool.hatch.build.targets.wheel] packages = ["devpilot"]` already ships non-Python files inside the package.
- The Reviewer prompt says the lens is "named in your briefing", because no `Slice` carries it (see change requests).

## Contract change requests
1. `judge.select`: `TournamentResult.winner` is a plain `str` and the `winner_passed_gates` validator exists, but there is no way to say "no eligible candidate". The prompt tells the model to submit `none` in that case; the validator must accept this or the orchestrator must never call the judge with zero eligible candidates (docs/11 §5 implies the latter). Please confirm.
2. `reviewer.review`: add a `Slice` (or ModeSpec field) for the assigned lens. Today the lens can only travel in free text.
3. `ChangeReport` has no `disputes` field (docs/03 had one). Samurai modes dispute via `msg.send`, but `samurai.explore` and `single.baseline` have no such tool, which is probably fine.
4. `shogun.plan` lists `graph.callers` twice in its tuple (READ already contains it). Harmless; the prompt de-duplicates.
5. `shogun.decide` has no `request` slice; it relies on spec and plan alone.

## Known gaps
- Prompts are untested against a live model; quality of JSON examples is validated structurally only.
- Slice names are written as the enum values (for example `repo_map`); the prompt compiler should label briefing sections with the same names.
- Semantic validators (evidence existence, fingerprint match) are not exercised by the examples, which use plausible ids.

## Prompts I'm least confident about
- `verifier.verify`: densest prompt; the number of techniques may be more than a model uses within its step budget. Consider trimming after first live runs.
- `shogun.decide`: the tension between "prefer cheapest action" and the guards' forced actions may need tuning once real dossiers exist.
- `security.inspect`: taint analysis guidance assumes `scan.taint` returns source-to-sink paths in a form the model can copy into `TaintPath`.
- `sentinel.author_acceptance`: assumes red is verified by running tests that the model itself wrote.
