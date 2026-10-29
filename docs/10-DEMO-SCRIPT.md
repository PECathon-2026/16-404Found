# 10 — Demo Script & Reference Run Log

## 1. Three-minute judge demo

| Time | Show | Say |
|---|---|---|
| 0:00 | Title slide: "Plan like a Shogun… Adapt until complete" + architecture diagram | "DevPilot turns a request into a tested, reviewed change — and never claims success without evidence." |
| 0:20 | Terminal: `devpilot run --repo fixtures/fx2_bug_pagination "Users report the last page…"` | "A vague bug report. No failing test given." |
| 0:35 | Live view: Scout's RepoBrief (test cmd, conventions) → Shogun's ACs | "Every acceptance criterion names how it will be verified." |
| 0:55 | Samurai attempt 1 → Sentinel **red** → triage message to Samurai | "Here's the feedback loop: Sentinel's evidence routes to the developer…" |
| 1:15 | Decision panel: `RETRY_SAME_AGENT` citing E-0021; attempt 2 with **new hypothesis** | "…and the developer changes its hypothesis because of that evidence." |
| 1:35 | Parallel checks: Verifier probe **FAILS** AC-2 with a counterexample | "The verifier never saw the developer's reasoning. It wrote its own test and caught an edge case." |
| 1:55 | Attempt 3 → all green → Apply Gate | "Nothing touches the real repo without a human." |
| 2:10 | Approve → `REPORT.md`: Verified vs. Claims sections | "Verified rows link to real test runs on the final code. Claims are labelled as claims." |
| 2:30 | Quick cuts: FX5c escalation (no infinite loop), FX4 SQLi caught, `POLICY_DENIED` on `rm` | "Bounded autonomy: it knows when to stop and ask." |
| 2:50 | Eval table multi vs single | "Coordination earns its keep — here's the data." |

Backup: `devpilot run ... --replay demo/fx2.cassette.jsonl` (LLM responses replayed; tools and tests execute for real).

## 2. Reference run log (target shape for FX2)

> ⚠️ **Illustrative target, not a real result.** This shows the format and the loop we must reproduce. The committed `demo/` folder must contain an actual run's `events.jsonl` and `REPORT.md`.

```
14:30:01 MISSION   M-20261030-1430-7c1d created  repo=fixtures/fx2_bug_pagination
14:30:01 WORKSPACE worktree runs/M-…/workspace on devpilot/M-…
14:30:03 scout     fs.list(".", depth=3)                       — "map layout"
14:30:05 scout     fs.read("pager/paginate.py")                — "request mentions pages"
14:30:08 scout     test.run()                    E-0003  12 passed            (baseline GREEN)
14:30:15 scout     ▶ RepoBrief: test_cmd=[python -m pytest -q]; conventions: snake_case,
                     type hints, docstrings Google-style; risk: "no test for partial last page"
14:30:24 shogun    ▶ MissionSpec  AC-1 last page holds remainder items       [new_test]
                                  AC-2 page_count correct incl. empty input   [probe]
                                  AC-3 baseline tests still pass             [existing_test]
                     ambiguity=low  assumption: "empty input → 0 pages (per docstring L12)"
14:30:30 shogun    ▶ Plan v1: T1 "Fix pagination remainder + regression test" files=[pager/paginate.py, tests/test_paginate.py]
14:30:31 ORCH      spawn samurai#1 → T1
14:30:40 samurai#1 search.code("def paginate|page_count")     — "locate pagination logic"
14:30:52 samurai#1 fs.edit(pager/paginate.py)                  — "slice end used size*page, off by one"
14:30:58 samurai#1 fs.edit(tests/test_paginate.py)             — "add test_last_page_partial"
14:31:04 samurai#1 test.run("tests/test_paginate.py") E-0012  1 failed (self-check)
14:31:10 samurai#1 ▶ ChangeReport attempt 1  status=partial  claims: "slice fixed"
14:31:15 sentinel  test.run()                    E-0014  12 passed, 1 failed  verdict=RED
14:31:22 sentinel  fs.read("pager/paginate.py", 35, 50)        — "traceback points at page_count"
14:31:27 sentinel  ▶ FINDING F-0003 → task:T1  fp=a91f03  "page_count uses floor division; remainder
                     page never generated (L41). Use ceil division." confidence=high
14:31:30 shogun    ▶ DECISION D-0002 RETRY_SAME_AGENT T1  cites=[E-0014,F-0003]
                     "first occurrence of a91f03; triage specific & high confidence"
14:31:31 ORCH      samurai#1 attempt 2 (inbox: F-0003)
14:31:45 samurai#1 fs.edit(pager/paginate.py)                  — "F-0003: -(-total // size) for ceil"
14:31:51 samurai#1 test.run("tests/test_paginate.py") E-0017  passed
14:31:58 sentinel  test.run()                    E-0018  13 passed  verdict=GREEN  regressions=0
14:31:59 ORCH      checkpoint commit 9be1a40 ; CHECKING (parallel)
14:32:10 verifier  fs.write_probe("test_probe_AC_2.py")         — "AC-2 incl. empty input"
14:32:14 verifier  test.run(probes)              E-0021  1 failed: page_count(0, 10) == 1, expected 0
14:32:20 reviewer  ▶ ReviewReport approve  findings: [nit: magic expression → helper _ceil_div]
14:32:22 security  scan.secrets E-0019 clean; scan.static(bandit) E-0020 clean ▶ pass
14:32:25 verifier  ▶ Verdict REJECT  AC-1 PASS  AC-2 FAIL (counterexample total=0)  AC-3 PASS
14:32:31 shogun    ▶ DECISION D-0003 RETRY_SAME_AGENT T1 cites=[E-0021]  "new fingerprint, concrete counterexample"
14:32:45 samurai#1 fs.edit(pager/paginate.py)                  — "guard total==0 → 0; add _ceil_div helper (review nit)"
14:32:50 samurai#1 fs.edit(tests/test_paginate.py)             — "add test_empty_has_no_pages"
14:32:58 sentinel  test.run()                    E-0024  14 passed  GREEN
14:33:10 verifier  test.run(probes)              E-0026  passed  ▶ ACCEPT (diff_sha 3f9c2e1)
14:33:12 reviewer  ▶ approve ; security ▶ pass
14:33:13 GATE      AWAITING_APPLY  (human)
14:33:40 HUMAN     approve
14:33:41 APPLY     git merge --ff-only devpilot/M-…   OK
14:33:42 REPORT    COMPLETED_VERIFIED  ACs 3/3 VERIFIED  fix_cycles 2  tokens 141k
```

### What this log proves (map to criteria)
- **Feedback loop changing behaviour:** F-0003 → attempt 2 changes *which line* and *which hypothesis*; E-0021 counterexample → attempt 3 adds a guard + a test.
- **Coordination:** Sentinel → Samurai finding; Reviewer nit folded into attempt 3; Verifier independent.
- **Tool intelligence:** every call has a rationale; search before edit; single-test self-check before full suite.
- **Evidence-based completion:** VERIFIED rows reference E-0024/E-0026 bound to final `diff_sha`.
