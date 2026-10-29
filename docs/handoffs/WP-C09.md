# WP-C09 - Report engine and memory
**Status:** ready-for-review
**Branch:** wp/c09-report (from wp/all-in-one)

## What I built
`devpilot/report/`
- `model.py`: pydantic `MissionReport` (header, `verified` / `failed` / `unverified` AC rows, `claims`, `feedback_loops`, `strategy_changes`, `guard_overrides`, `plan_history`, `review_security`, `tests`, `changed_files`, `budget`, `human_decisions`, `evidence_appendix`, `consistency_errors`).
- `engine.py`: `build_report(mission, events, *, final_tree_sha, diff_names=None, diff_text=None)` is pure and deterministic. AC status comes only from `ac_rules.ac_status` (confidence from `ac_rules.confidence` / the stored `confidence_by_ac`). `consistency_check(report, mission)` flags (a) any VERIFIED row without passing execution evidence (kind in `EXECUTION_KINDS`, exit 0) bound to `final_tree_sha`, (b) any AC the projected mission calls VERIFIED that the recomputed report does not, (c) COMPLETED_VERIFIED with unverified must-ACs or not applied. Also `derive_final_tree_sha`, `parse_diff`.
- `markdown.py` (`render_markdown`), `html.py` (`render_html(report, events)`: inline CSS, dark/light, collapsible timeline, `<script type="application/json" id="report-data">`; `<` is escaped as `<` so report text cannot close the script).
- `writer.py`: `write_report(mission, store, workspaces=None, *, out_dir, force=False)` writes `REPORT.md`, `report.html`, `mission.json` (`{"report": ..., "mission": ...}`) and `final.diff` atomically (temp file + `os.replace`). On a failed consistency check it raises `ReportConsistencyError` and writes only `REPORT_REFUSED.txt`; with `force=True` it writes everything with a red banner. `make_report_writer(store, workspaces, runs_dir, *, force=False)` returns the `Callable[[Mission], Awaitable[None]]` hook. It emits no events.

`devpilot/memory/`
- `store.py`: `SqliteMemoryStore(path, *, use_fts=None)` (stdlib sqlite3 via `asyncio.to_thread`, connection per call). FTS5 table `memory_fts` with bm25 (trigger weighted 2x); automatic LIKE + keyword-overlap fallback when FTS5 is missing (`fts5_available()`; `use_fts=False` forces it). Score = relevance x confidence; recall bumps `uses` and `last_used_at`. `write` dedups on `(repo_key, kind, normalised trigger)`: content replaced, evidence ids merged, confidence +0.1 (cap 1.0). `reinforce` clamps to [0, 1]. Extras: `get`, `list_items`. Enabling FTS on a db created without it backfills the index.
- `extract.py`: `repo_key_for(path)` = `sha1(abspath)[:12]`; `extract_memories(mission, report)`; `lessons_from_reflection(mission, reflection)` (drops lessons whose evidence ids are not all in `mission.evidence`; `Reflection` submissions on the mission are picked up automatically).

Tests (`tests/report`, `tests/memory`; 41 tests): the FX2 scenario is run for real through `tests/orchestrator/orch_helpers` (`tests/report/fx2_support.py`). Covered: verified/failed/claims split, exactly 2 feedback loops with exact chains, Markdown evidence ids, HTML parse + JSON round-trip + script-injection escaping, forged-evidence consistency check and writer refusal / force banner, hook-time (REPORTING) projection, the real hook running inside the orchestrator, FTS and fallback recall (parametrised), dedup, clamping, persistence, extraction (procedural lesson with the fingerprint), reflection filtering, and the golden file.

Golden: `tests/report/golden/fx2_report.md` (timestamps and wall clock normalised in the test). Sample copy: `docs/samples/fx2_report_scripted.md`.

## How to verify
```
python -m pytest -q tests/report tests/memory   -> 41 passed
python -m pytest -q                              -> 677 passed
python -m ruff check .                           -> All checks passed
python -m mypy devpilot/report devpilot/memory   -> Success: no issues found in 9 source files
```

## Wiring
Orchestrator (another packet owns `wiring.py`):
```python
from devpilot.report.writer import make_report_writer
orch = Orchestrator(bb, runtime, workspaces, tests, human, settings,
                    report_writer=make_report_writer(event_store, workspaces, runs_dir))
```
Files land in `<runs_dir>/<mission_id>/` next to `events.jsonl`. The orchestrator emits `REPORT_WRITTEN` after the hook returns and only logs if it raises, so a consistency refusal leaves `REPORT_REFUSED.txt` and no `REPORT.md`; pass `force=True` if a banner-marked report is preferred over none. The hook runs while the mission is still `REPORTING`, so the report shows the outcome as "(projected ...)" using the same rule as `Orchestrator._terminal` (applied and every `must` AC verified). The final tree sha is `workspaces.tree_sha("main")`, falling back to the APPLIED event / last verdict when no workspaces are given.

Memory (`ContextServices`, runtime): `SqliteMemoryStore(Path.home() / ".devpilot" / "memory.sqlite")` satisfies `ports.MemoryStore`; pass it wherever `ContextServices` is built and compute `repo_key = repo_key_for(mission.repo_path)`. Writing at REPORTING (the orchestrator does not do this yet, see its handoff gaps):
```python
report = build_report(mission, events, final_tree_sha=sha)
for item in extract_memories(mission, report):
    await memory.write(item)   # then emit MEMORY_WRITTEN
```
Before Scout / Shogun / Samurai briefings: `await memory.recall(repo_key, query, ["semantic", "procedural", "episodic"], k=5)` (label results "may be stale - verify"; emit MEMORY_RECALLED). For procedural recall use the triage `error_type + fingerprint + fix_direction` as the query.

## Deviations
- `write_report(mission, store, workspaces=None, out_dir)` in the packet is not valid Python; `out_dir` is keyword-only (plus `force`).
- `build_report` has one extra optional kwarg, `diff_text`, for +/- line counts; `diff_names` alone gives names only.
- `RepoBrief` has no `assumptions` field; I use `RepoBrief.open_questions` alongside `MissionSpec.assumptions`. Security findings have no `proven` flag: an LLM-sourced finding without evidence ids or exploit probe counts as an unproven claim; scanner-sourced findings do not.
- Claims and review/security sections use the latest submission per task / lens only (earlier rounds were superseded by a new tree).
- Decision ids are `D-0001...` numbered by DECISION event order (the contract gives decisions no id). Verifier-triggered loops cite the failing checks' evidence, else the execution evidence on the rejected tree, plus the verifier finding id.
- Fix cycles are `max(budget.fix_cycles, BUDGET_WARNING / MISSION_FINISHED payloads)` and wall clock is `max(budget.wall_clock_s, event span)`, because the projector on this base does not apply the orchestrator's `BUDGET_WARNING` counters (C05 contract request 1). The span includes human wait time.
- Semantic memories are written only if every lens's latest ReviewReport is `approve`, and only with at least one existing evidence id. Convention evidence is the verified AC evidence (conventions have none of their own).
- `trigger` is quoted in SQL (keyword); FTS columns are `trigger_text` / `content_text`.

## Contract change requests
None required. Nice to have: (1) DECISION payloads should carry a decision id instead of the report numbering them; (2) the projector should apply `BUDGET_WARNING` fix-cycle counters (already requested in C05); (3) `MemoryItem` could expose `last_used` (the DB has `last_used_at`, the model does not).

## Known gaps
- Loop reconstruction relies on `DECISION.trigger_event_seq` and event order; a multi-task decision pass shares findings by `routed_to`. REPLAN / TOURNAMENT loops pick the next IN_PROGRESS attempt of the same task, else any task.
- Not wired by `wiring.py` / CLI yet; nothing emits MEMORY_WRITTEN / MEMORY_RECALLED.
- Embedding similarity (docs/11 s10) is not implemented; keyword/bm25 only. No decay of contradicted memories.
- `report.html` is intentionally plain (no diff viewer); `final.diff` is written beside it.
