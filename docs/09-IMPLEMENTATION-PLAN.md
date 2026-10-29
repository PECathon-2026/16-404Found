# 09 — Implementation Plan & Task Checklists

> **Superseded in part:** the team split and per-person checklists (§2–§3) are replaced by the Claude/Gemini work packets in [`13-BUILD-ORCHESTRATION.md`](13-BUILD-ORCHESTRATION.md). The repo layout, Definition of Done and cut list below still apply.

Assumptions: **4 engineers, ~36 hours**. Adjust phase lengths proportionally. Rule: **walking skeleton end-to-end by H8**, then deepen. Never let a "cool" feature block the flagship demo (FX2).

## 1. Repository layout (target)

```
404Found/
├── README.md
├── CLAUDE.md                      # instructions for AI coding assistants on this repo
├── pyproject.toml                 # deps: anthropic, pydantic>=2, typer, rich, tomli (py<3.11)
├── devpilot.example.toml          # copy → devpilot.toml
├── config/policy.toml             # command/file policy (see 05)
├── devpilot/
│   ├── cli.py                     # typer: run, resume, approve, reject, report, eval, abort
│   ├── config.py
│   ├── core/
│   │   ├── models.py              # all pydantic schemas (03, 04)
│   │   ├── events.py              # Event types + JSONL writer
│   │   ├── blackboard.py          # projection + ownership checks
│   │   ├── bus.py                 # AgentMessage, inboxes
│   │   ├── orchestrator.py        # mission state machine + scheduling
│   │   ├── guards.py              # budgets, fingerprint repeats, circuit rules
│   │   ├── fingerprint.py
│   │   └── workspace.py           # git worktree lifecycle, checkpoints, apply
│   ├── agents/
│   │   ├── runner.py              # shared tool-use loop (03 §9)
│   │   ├── specs.py               # AgentSpec per role: model, tools, submit tool
│   │   └── briefings.py           # render context per role (information hiding for Verifier)
│   ├── prompts/                   # shogun.md, scout.md, samurai.md, sentinel.md, verifier.md, reviewer.md, security.md, single.md
│   ├── tools/
│   │   ├── gateway.py             # validate → permission → policy → breaker → exec → evidence
│   │   ├── policy.py
│   │   ├── fs.py  search.py  shell.py  testrun.py  git.py  scanners.py  memory.py  board.py
│   │   └── junit.py               # JUnit XML parser
│   ├── llm/
│   │   ├── client.py              # Anthropic wrapper: retries, semaphore, token accounting
│   │   └── cassette.py            # record / replay
│   ├── memory/store.py
│   ├── report/
│   │   ├── engine.py              # deterministic AC status rules (06 §6)
│   │   ├── markdown.py
│   │   └── html.py                # single-file HTML with embedded JSON + timeline
│   └── ui/live.py                 # rich Live dashboard
├── fixtures/fx1..fx5/
├── eval/                          # results.json / results.md (generated)
├── runs/                          # gitignored mission outputs
├── demo/                          # recorded cassettes + sample run logs committed for judges
└── tests/                         # unit tests for DevPilot itself
```

## 2. Team split

| Owner | Track | Owns |
|---|---|---|
| **P1 — Core** | Orchestrator, state machines, blackboard, bus, guards, workspace | `core/*` |
| **P2 — Tools & Safety** | Gateway, policy, all tools, scanners, circuit breakers, sandbox tests | `tools/*`, `config/policy.toml` |
| **P3 — Agents** | Runner, LLM client, cassettes, prompts, briefings, submit schemas | `agents/*`, `llm/*`, `prompts/*` |
| **P4 — Proof** | Fixtures, eval harness, report engine, HTML report, live UI, README, demo | `fixtures/*`, `report/*`, `ui/*`, `eval/`, docs |

Interfaces are frozen at H2 (`core/models.py` + tool result envelope). Change them only with a team ping.

## 3. Phases & checklists

### Phase 0 — Foundations (H0–H2) — all
- [ ] `pyproject.toml`, package skeleton, `ruff`, `pytest` set up
- [ ] `core/models.py`: Mission, MissionSpec, AC, Task, Plan, Finding, Decision, Evidence, AgentMessage, RepoBrief, ChangeReport, TestReport, VerifierVerdict, ReviewReport, SecurityReport
- [ ] Tool result envelope + error codes agreed
- [ ] `devpilot.example.toml`, `.gitignore` (`runs/`, `.env`)
- [ ] FX2 fixture written first (flagship)

### Phase 1 — Walking skeleton (H2–H8)
**P1**
- [ ] `events.py` JSONL writer; `blackboard.apply(event)`
- [ ] `workspace.py`: create worktree / shadow repo, diff, checkpoint commit
- [ ] Orchestrator linear path: RECON → ANALYZING → PLANNING → EXECUTING → TESTING → AWAITING_APPLY → REPORTING
**P2**
- [ ] Gateway pipeline with path jail + allowlist (deny by default)
- [ ] `fs.list/read/edit/write`, `search.code` (rg + python fallback), `git.diff/status`
- [ ] `test.run` with JUnit parsing
- [ ] Unit tests: path traversal (`../`, absolute, symlink), denied commands, shell metachar rejection
**P3**
- [ ] `llm/client.py` (Anthropic Messages API, tools, retries/backoff, token counting)
- [ ] `agents/runner.py` loop with submit-tool termination & validation errors fed back
- [ ] Prompts v0: Scout, Shogun(analyze/plan), Samurai, Sentinel
**P4**
- [ ] FX1, FX3 fixtures + hidden tests
- [ ] `report/engine.py` AC status rules + `markdown.py`
- [ ] Minimal `rich` progress printing of events
- **✅ Exit criterion H8:** `devpilot run --repo fixtures/fx2_bug_pagination "..."` produces a diff + REPORT.md (even if not all ACs pass).

### Phase 2 — Feedback loops & independence (H8–H18)
**P1**
- [ ] DECIDING state + `Shogun.decide` integration + guards table (04 §6.3)
- [ ] Task inboxes; messages injected into briefings
- [ ] Fingerprint repeat tracking; `STRATEGY_CHANGED` events
- [ ] INVESTIGATE (Scout re-invocation) and REPLAN (plan versioning, task cancel/add)
- [ ] Parallel Samurai scheduling with file locks; `asyncio.gather` checks
**P2**
- [ ] Circuit breaker + `TOOL_UNAVAILABLE` fallback flow; `DEVPILOT_DISABLE_TOOLS`
- [ ] Test-assertion protection
- [ ] Output truncation + redaction + evidence files with `workspace_sha`
- [ ] `fs.write_probe`, probes dir test execution
**P3**
- [ ] Verifier with information-hiding briefing + probe writing
- [ ] Sentinel triage prompt quality pass on FX2/FX3
- [ ] Cassette record/replay
- [ ] Shogun decide/adjudicate prompts; decision cites evidence IDs
**P4**
- [ ] FX4, FX5 fixtures + `scenario.toml` + answers files
- [ ] Live dashboard: plan board, agent panel, tool feed, test status
- **✅ Exit criterion H18:** FX2 shows ≥1 test-failure loop and ≥1 verifier loop end-to-end, recorded cassette saved.

### Phase 3 — Shadow Council & Human Gate (H18–H26)
**P1**
- [ ] CHECKING state (parallel verify/review/security), stale-verdict guard
- [ ] Dispute protocol + adjudication + escalation
- [ ] Human gates: clarification, command approval, escalation, apply (+ `approve/reject/resume` CLI)
- [ ] Apply: ff-merge, dirty-target refusal
**P2**
- [ ] `scan.secrets`, `scan.static` (bandit + fallback AST rules), introduced-vs-preexisting
- [ ] Sandbox test suite green on Windows + Linux
**P3**
- [ ] Reviewer + Security prompts; routing findings to tasks
- [ ] Memory store write/recall; inject into briefings
- [ ] `--mode single` baseline agent
**P4**
- [ ] `report/html.py` (timeline, diff, evidence links)
- [ ] `devpilot eval` harness + hidden test grading
- **✅ Exit criterion H26:** all 5 fixtures run to a terminal state; FX4 catches all 3 planted issues.

### Phase 4 — Proof & polish (H26–H33)
- [ ] Run eval: multi vs single, 3 runs each → `eval/results.md` (real numbers only)
- [ ] Commit demo cassettes + one full run folder to `demo/` (run log w/ feedback loop = deliverable)
- [ ] README final pass: diagrams, setup, tools list, limitations
- [ ] Record 3-min backup demo video
- [ ] Prompt tuning only where eval shows failures

### Phase 5 — Buffer (H33–H36)
- [ ] Bug fixes only. Feature freeze at H33.
- [ ] Dry-run the demo script twice (live + replay).

## 4. Definition of Done (per component)
- Typed with pydantic models from `core/models.py`
- Unit tests for deterministic parts (gateway, policy, guards, fingerprint, report engine, junit parser) — **these must not call an LLM**
- Emits events for every externally visible action
- No hard-coded paths; works on Windows and Linux

## 5. Priority cut list (if behind schedule, cut from the bottom)
1. ~~Docker sandbox~~ (already stretch)
2. Node test support
3. HTML report (keep Markdown)
4. Persistent memory
5. Single-agent baseline comparison
6. Parallel Samurai (keep sequential, keep parallel checks)
7. Plan-approval gate

**Never cut:** baseline test run, Sentinel triage loop, Verifier independence, evidence-based report, path jail/allowlist, apply gate, budgets/guards.
