# PROGRESS-TRACKER.md — DevPilot Living Execution Tracker

> Rules for editing this file: §D. Canon: [AGENTS.md §0](AGENTS.md). Task definitions: [PLAN.md §C](PLAN.md). Architecture: [ARCHITECTURE.md](ARCHITECTURE.md). UI: [UI-REGISTRY.md](UI-REGISTRY.md).
> **Accuracy rule (§H):** this file records only what was actually done and actually run. Planned ≠ implemented ≠ tested ≠ verified.

---

## A. Project Overview

| Field | Value |
|---|---|
| Last updated | 2026-10-30 |
| Project stage | **Phase −1: blueprint complete; no code written.** Next: Phase 0. |
| MVP completion | **0 / 74 P0 tasks completed** (0 %). Total backlog 85 tasks (74 P0, 9 P1, 2 P2). |
| Repository evidence | At authoring time `git log` shows 2 commits (`Initial commit`, `docs: remove README.md`) on `main`; the working tree contained no source files before the five blueprint documents were added. Nothing in `backend/`, `frontend/` or `eval/` exists. |
| Active blockers | See §B. |
| Upcoming milestones | M1: Phase 0 + Phase 1 green (`make check`, API + SSE). M2: Phase 2 sandbox escape suite green. M3: first live SC-1 mission through plan→dev→test. M4: SC-3 feedback loop recorded. M5: verifier + approval gate. M6: UI MVP. M7: SC-1…SC-7 recorded. M8: README + demo. |
| High-priority risks | RK-1 loops/budget · RK-2 test tampering · RK-3 sandbox escape · RK-4 prompt injection · RK-5 structured-output flakiness · RK-7 UI scope creep (full list: [PLAN.md §A.6](PLAN.md)). |

### Progress by phase (counts of tasks by status; update when you change a row)

| Phase | Name | Total | In progress / review / testing | Verified | Completed |
|---|---|---|---|---|---|
| 0 | Foundations | 6 | 0 | 0 | 0 |
| 1 | Backend infra & DB | 11 | 0 | 0 | 0 |
| 2 | Tools & sandbox | 14 | 0 | 0 | 0 |
| 3 | Orchestration & planner | 8 | 0 | 0 | 0 |
| 4 | Developer/Tester/Security | 6 | 0 | 0 | 0 |
| 5 | State, comms, feedback | 8 | 0 | 0 | 0 |
| 6 | Verification & approval | 6 | 0 | 0 | 0 |
| 7 | Frontend | 13 | 0 | 0 | 0 |
| 8 | Integration & evaluation | 8 | 0 | 0 | 0 |
| 9 | Demo & deployment | 5 | 0 | 0 | 0 |

---

## B. Blockers and Open Questions

| ID | Description | Affects | Raised by | Date | Status |
|---|---|---|---|---|---|
| BL-1 | No model-provider API key configured yet (needed for live agent runs; FakeLLM covers tests). | T3.04+, T8.03+ | blueprint author | 2026-10-30 | OPEN |
| BL-2 | Target host Docker availability unknown (affects T2.04, demo mode). Fallback: local-jail (documented weaker). | T2.04, T2.14, T9.03 | blueprint author | 2026-10-30 | OPEN |
| BL-3 | Final team size/owner assignment not recorded; all owners `unassigned`. | all | blueprint author | 2026-10-30 | OPEN |
| Q-1…Q-9 | Open design decisions DD-1…DD-9 with defaults: [PLAN.md §G](PLAN.md). Follow defaults until changed. | various | blueprint author | 2026-10-30 | OPEN |

Note on dependency order: T4.01–T4.03 depend on T5.01 (message bus) and T5.08 (`mission.*` tools), which are *pulled forward* from Phase 5 because agents need them to communicate. Schedule T5.01/T5.08 immediately after Phase 3.

---

## C. Task Tracking

### Status definitions

| Status | Meaning |
|---|---|
| NOT_STARTED | Not begun; at least one dependency is not yet `VERIFIED`/`COMPLETED`. |
| READY | All dependencies `VERIFIED`/`COMPLETED`; nobody has claimed it. |
| IN_PROGRESS | Claimed by an owner who is actively changing files. |
| BLOCKED | Cannot proceed; a blocker row in §B explains why. |
| IN_REVIEW | Implementation finished; awaiting peer/agent review. |
| TESTING | Review done; required tests being executed. |
| VERIFIED | Required tests actually executed and green, acceptance criteria demonstrated, evidence attached. |
| COMPLETED | Verified **and** integrated into the main line; docs updated. |

### Backlog (stable IDs `T<phase>.<nn>`; priorities per [PLAN.md §B](PLAN.md))

Initial statuses: `READY` only where a task has no dependencies (T0.01, based on dependency data, not on code evidence). Everything else `NOT_STARTED`. No task has any implementation evidence.

| ID | Task | Phase | Priority | Owner | Status | Dependencies | Evidence |
|---|---|---|---|---|---|---|---|
| T0.01 | Monorepo scaffold (backend/, frontend/, eval/, docker/, runs/ ignored), .gitignore | 0 | P0 | unassigned | READY | — | — |
| T0.02 | Backend tooling: pyproject, ruff, mypy --strict, pytest config | 0 | P0 | unassigned | NOT_STARTED | T0.01 | — |
| T0.03 | Frontend scaffold: Next.js App Router, TS strict, Tailwind, shadcn/ui, ESLint | 0 | P0 | unassigned | NOT_STARTED | T0.01 | — |
| T0.04 | `make check` (ruff, mypy, pytest, tsc, eslint) as the single quality gate | 0 | P0 | unassigned | NOT_STARTED | T0.02, T0.03 | — |
| T0.05 | Canonical enums + Pydantic models (state/enums.py, state/models.py) + enum-parity test vs AGENTS §0.3 | 0 | P0 | unassigned | NOT_STARTED | T0.02 | — |
| T0.06 | Settings loader (pydantic-settings) + `.env.example` (placeholders only) | 0 | P0 | unassigned | NOT_STARTED | T0.02 | — |
| T1.01 | SQLAlchemy models + Alembic migration for all ARCH §D tables | 1 | P0 | unassigned | NOT_STARTED | T0.05 | — |
| T1.02 | DB repositories (one per aggregate), async session | 1 | P0 | unassigned | NOT_STARTED | T1.01 | — |
| T1.03 | FastAPI app factory, DI `Deps`, error model, request-id middleware, /health | 1 | P0 | unassigned | NOT_STARTED | T0.06 | — |
| T1.04 | Mission API: create / list / get | 1 | P0 | unassigned | NOT_STARTED | T1.02, T1.03 | — |
| T1.05 | Repository registry API (local path / git URL import) | 1 | P0 | unassigned | NOT_STARTED | T1.02, T1.03 | — |
| T1.06 | Event bus + `audit_events` persistence + SSE endpoint with Last-Event-ID resume | 1 | P0 | unassigned | NOT_STARTED | T1.02, T1.03 | — |
| T1.07 | Structured logging (structlog) + audit writer + redaction hook | 1 | P0 | unassigned | NOT_STARTED | T1.03 | — |
| T1.08 | State Manager (versioned writes, lifecycle transition guard from AGENTS §0.4) | 1 | P0 | unassigned | NOT_STARTED | T0.05, T1.02 | — |
| T1.09 | Mission control endpoints: start / pause / resume / cancel / respond | 1 | P0 | unassigned | NOT_STARTED | T1.08, T1.04 | — |
| T1.10 | LLM provider abstraction (Anthropic, Gemini, OpenAI-compat) + FakeLLM + structured output + router skeleton | 1 | P0 | unassigned | NOT_STARTED | T0.06 | — |
| T1.11 | Token/cost ledger + budget enforcement hooks (`model_calls`, `Budgets`) | 1 | P0 | unassigned | NOT_STARTED | T1.10, T1.01 | — |
| T2.01 | Workspace manager: copy repo (exclude secrets), git baseline commit, base_commit | 2 | P0 | unassigned | NOT_STARTED | T1.05 | — |
| T2.02 | Path jail (realpath, symlink, traversal) + property tests | 2 | P0 | unassigned | NOT_STARTED | T0.02 | — |
| T2.03 | Local-jail runner (rlimits, scrubbed env, timeouts, process-group kill) — fallback mode | 2 | P0 | unassigned | NOT_STARTED | T2.01, T2.02, T2.05 | — |
| T2.04 | Docker runner (network none, read-only root, non-root, caps dropped, limits) | 2 | P0 | unassigned | NOT_STARTED | T2.01, T2.02, T2.05 | — |
| T2.05 | Command policy: profiles, allow/deny lists, metacharacter rejection (≥ 40 table cases) | 2 | P0 | unassigned | NOT_STARTED | T0.02 | — |
| T2.06 | Tool interface, registry, per-agent permission matrix, ToolResult schema, tool_calls persistence | 2 | P0 | unassigned | NOT_STARTED | T1.01, T1.07, T0.05 | — |
| T2.07 | fs tools: read / list / search / edit / create / delete | 2 | P0 | unassigned | NOT_STARTED | T2.02, T2.06 | — |
| T2.08 | git tools: status / diff / checkpoint / rollback + patch export + patch_sha256 | 2 | P0 | unassigned | NOT_STARTED | T2.01, T2.06 | — |
| T2.09 | `shell.run` tool with profiles | 2 | P0 | unassigned | NOT_STARTED | T2.03, T2.05, T2.06 | — |
| T2.10 | `check.test/lint/build` + command detection (pytest/unittest/npm) + parsers | 2 | P0 | unassigned | NOT_STARTED | T2.09 | — |
| T2.11 | `sec.scan_secrets`, `sec.scan_patterns`, `sec.audit_deps` (unavailable → ENV_MISSING_TOOL) | 2 | P0 | unassigned | NOT_STARTED | T2.06 | — |
| T2.12 | Tool-call logging + secret redaction pipeline (G5) + truncation/artifacts | 2 | P0 | unassigned | NOT_STARTED | T2.06, T1.07 | — |
| T2.13 | Test-tamper detector (existing tests modified/deleted/skipped/weakened) | 2 | P0 | unassigned | NOT_STARTED | T2.08 | — |
| T2.14 | Sandbox escape test suite (G1–G4, G8) | 2 | P0 | unassigned | NOT_STARTED | T2.04, T2.07, T2.09 | — |
| T3.01 | LangGraph skeleton: GraphState, nodes stubs, hub-and-spoke edges, SqliteSaver (checkpoint spike) | 3 | P0 | unassigned | NOT_STARTED | T1.08, T1.10 | — |
| T3.02 | Master decision node: MasterDecision schema, guard, deterministic fallback policy | 3 | P0 | unassigned | NOT_STARTED | T3.01, T1.08, T1.10 | — |
| T3.03 | Watchdog: failure fingerprints, counters/limits, wait-for graph, heartbeat | 3 | P0 | unassigned | NOT_STARTED | T3.01 | — |
| T3.04 | Planner agent: recon + PlanResult (criteria with verification methods, DAG, ambiguities) | 3 | P0 | unassigned | NOT_STARTED | T3.07, T2.07, T2.10, T3.05 | — |
| T3.05 | Plan validator (acyclic DAG, criterion→task coverage, method present) | 3 | P0 | unassigned | NOT_STARTED | T0.05 | — |
| T3.06 | AWAITING_HUMAN interrupt/resume via human_input node + /respond | 3 | P0 | unassigned | NOT_STARTED | T3.01, T1.09 | — |
| T3.07 | Agent runtime base: tool loop, structured output, budgets, heartbeat, untrusted-content wrapping | 3 | P0 | unassigned | NOT_STARTED | T1.10, T2.06, T1.11 | — |
| T3.08 | Replan flow (REPLAN_REQUEST → delta, SUPERSEDED tasks, criteria_version bump) | 3 | P0 | unassigned | NOT_STARTED | T3.04, T3.02, T3.05 | — |
| T4.01 | Developer agent (tool selection policy, conventions, repair mode) | 4 | P0 | unassigned | NOT_STARTED | T3.07, T2.07, T2.08, T2.09, T2.10, T2.13, T5.01, T5.08 | — |
| T4.02 | Tester agent (baseline capture, classification, regression detection, rerun) | 4 | P0 | unassigned | NOT_STARTED | T2.10, T4.04, T3.07, T5.01, T5.08 | — |
| T4.03 | Security agent (scanners + LLM review + quality notes, evidence-based findings) | 4 | P0 | unassigned | NOT_STARTED | T2.11, T3.07, T5.01, T5.08 | — |
| T4.04 | Failure classifier / parsers (pytest, unittest, jest) with golden files | 4 | P0 | unassigned | NOT_STARTED | T2.10 | — |
| T4.05 | Repair task generation with failure_context + prior-attempt diffs | 4 | P0 | unassigned | NOT_STARTED | T4.04, T3.02 | — |
| T4.06 | Prompt library + prompt regression tests (FakeLLM + schema checks) | 4 | P1 | unassigned | NOT_STARTED | T4.01, T4.02, T4.03 | — |
| T5.01 | Message bus + envelope validation + ack/redelivery + idempotency (AGENTS §C) | 5 | P0 | unassigned | NOT_STARTED | T1.06, T1.08 | — |
| T5.02 | Critique / critique-response flows (developer↔tester, developer↔security) | 5 | P0 | unassigned | NOT_STARTED | T5.01, T4.01, T4.03 | — |
| T5.03 | Evidence precedence + conflict resolution (re-execute via EXECUTE, escalate on tie) | 5 | P0 | unassigned | NOT_STARTED | T5.02, T2.09 | — |
| T5.04 | Parallel read-only execution (tester ‖ security on immutable patch) | 5 | P1 | unassigned | NOT_STARTED | T4.02, T4.03 | — |
| T5.05 | Escalation handling + human-input payloads with evidence/options | 5 | P0 | unassigned | NOT_STARTED | T3.06, T3.03 | — |
| T5.06 | Parallel developer instances via git worktrees + file locks + merge-conflict repair (B-1) | 5 | P1 | unassigned | NOT_STARTED | T5.04, T2.08 | — |
| T5.07 | Persistent memory: repo conventions & failure→fix store (B-3) | 5 | P2 | unassigned | NOT_STARTED | T5.02 | — |
| T5.08 | `mission.*` tools (get_state, post_message, record_finding, update_task) | 5 | P0 | unassigned | NOT_STARTED | T1.08, T5.01 | — |
| T6.01 | Verifier process + isolated sandbox (base commit + patch only) | 6 | P0 | unassigned | NOT_STARTED | T2.04, T2.08, T3.05 | — |
| T6.02 | Verifier criterion methods (command, test_selector, static_check) + LLM judge with quoted evidence | 6 | P0 | unassigned | NOT_STARTED | T6.01, T1.10 | — |
| T6.03 | Completion gate + gate truth-table tests | 6 | P0 | unassigned | NOT_STARTED | T6.02, T4.03, T1.08 | — |
| T6.04 | Approval API: patch-hash binding, stale invalidation, apply patch to source repo with backup | 6 | P0 | unassigned | NOT_STARTED | T6.03, T2.08 | — |
| T6.05 | Final report generator (verified / unresolved / model-claims partition) + rollback | 6 | P0 | unassigned | NOT_STARTED | T6.04 | — |
| T6.06 | Single-agent baseline runner + comparison report (B-3) | 6 | P2 | unassigned | NOT_STARTED | T4.01, T3.02 | — |
| T7.01 | AppShell, Sidebar, design tokens (UI-REGISTRY §B) | 7 | P0 | unassigned | NOT_STARTED | T0.03 | — |
| T7.02 | API client, SSE hook (resume), mission store | 7 | P0 | unassigned | NOT_STARTED | T1.06, T0.03 | — |
| T7.03 | Missions list + MissionCard + MissionStatusBadge + MissionCreationWizard + RepositorySelector + ModelSelector | 7 | P0 | unassigned | NOT_STARTED | T7.01, T1.04, T7.02 | — |
| T7.04 | Mission Workspace layout + header + MissionTimeline + AgentCard strip | 7 | P0 | unassigned | NOT_STARTED | T7.01, T7.02 | — |
| T7.05 | AgentActivityFeed + ToolExecutionCard + TerminalOutput | 7 | P0 | unassigned | NOT_STARTED | T7.04 | — |
| T7.06 | TaskDependencyGraph | 7 | P0 | unassigned | NOT_STARTED | T7.04 | — |
| T7.07 | CodeDiffViewer (Monaco) | 7 | P0 | unassigned | NOT_STARTED | T7.04, T2.08 | — |
| T7.08 | TestResultPanel + SecurityFindingCard | 7 | P0 | unassigned | NOT_STARTED | T7.04 | — |
| T7.09 | ApprovalDialog + human-input dialog | 7 | P0 | unassigned | NOT_STARTED | T7.04, T6.04 | — |
| T7.10 | AgentNetworkGraph (React Flow) + Agent Network page | 7 | P1 | unassigned | NOT_STARTED | T7.02, T5.01 | — |
| T7.11 | Overview, Repositories, Execution History, Reports, Settings pages + EmptyState/ErrorBoundary | 7 | P1 | unassigned | NOT_STARTED | T7.03 | — |
| T7.12 | MetricsPanel + ExecutionReplay | 7 | P1 | unassigned | NOT_STARTED | T7.04, T1.11 | — |
| T7.13 | Accessibility + responsive pass (axe, keyboard, reduced motion) | 7 | P1 | unassigned | NOT_STARTED | T7.05, T7.06, T7.07, T7.08, T7.09 | — |
| T8.01 | Fixture repos for SC-1…SC-7 + expected.yaml | 8 | P0 | unassigned | NOT_STARTED | T0.01 | — |
| T8.02 | Eval harness (runs mission, asserts from persisted rows, writes runs/<scenario>/<ts>/) | 8 | P0 | unassigned | NOT_STARTED | T8.01, T1.04 | — |
| T8.03 | Run & record SC-1, SC-2, SC-3 (≥ 3 repeats SC-1) | 8 | P0 | unassigned | NOT_STARTED | T8.02, T6.05, T5.02, T4.05 | — |
| T8.04 | Run & record SC-4, SC-5 | 8 | P0 | unassigned | NOT_STARTED | T8.02, T6.05, T5.02 | — |
| T8.05 | Run & record SC-6, SC-7 | 8 | P0 | unassigned | NOT_STARTED | T8.02, T6.05, T5.05, T5.03 | — |
| T8.06 | Deterministic integration tests (FakeLLM): loops, limits, crash-resume, approval | 8 | P0 | unassigned | NOT_STARTED | T6.04, T5.05 | — |
| T8.07 | Tuning from eval failures (prompts, policies); re-run affected scenarios | 8 | P0 | unassigned | NOT_STARTED | T8.03, T8.04, T8.05 | — |
| T8.08 | Self security review of DevPilot (injection, traversal, secret leakage) | 8 | P1 | unassigned | NOT_STARTED | T2.14, T6.04 | — |
| T9.01 | README.md with all R-README sections (diagram, roles, comms/state, setup, tools+boundaries, approval, security assumptions, limitations) | 9 | P0 | unassigned | NOT_STARTED | T8.07 | — |
| T9.02 | Demo repo + script + recorded run log showing feedback loop (R-DEMO) | 9 | P0 | unassigned | NOT_STARTED | T8.03, T7.09 | — |
| T9.03 | docker compose deployment + fresh-clone setup test | 9 | P0 | unassigned | NOT_STARTED | T8.06 | — |
| T9.04 | Fallback assets: pre-recorded run, replay, scripted-run labelling | 9 | P1 | unassigned | NOT_STARTED | T9.02 | — |
| T9.05 | Submission checklist verification (PROGRESS-TRACKER §G) | 9 | P0 | unassigned | NOT_STARTED | T9.01, T9.02, T9.03, T9.04 | — |

### Task acceptance pointers
Each task's acceptance criteria, tests and DoD are the phase-level ones in [PLAN.md §C](PLAN.md) plus: the escape tests (T2.14) for G1–G8 in [ARCHITECTURE.md §G](ARCHITECTURE.md); scenario criteria in [PLAN.md §D](PLAN.md) for T8.03–T8.05; component specs in [UI-REGISTRY.md §F](UI-REGISTRY.md) for T7.*.

---

## D. Progress Update Rules (mandatory for every coding agent)

1. **Identify** the task ID you are working on (pick `READY`; never start a task whose dependencies aren't `VERIFIED`+).
2. **Mark `IN_PROGRESS`** with your agent name in Owner *before* editing code. One owner per task; one task per module at a time (module map: [PLAN.md §C](PLAN.md)).
3. **Record modified files** in your Execution History entry (§E) — exact paths.
4. **Record tests actually executed**: the exact command, and the real result line(s). If not run: write `NOT RUN — <reason>`.
5. **Attach evidence** in the task's Evidence cell: command + result summary + path to saved output under `runs/` or CI log reference. Evidence must be reproducible by someone else.
6. **Update blockers** (§B): add, update, or close rows with dates.
7. **Mark complete only after verification.** Ladder: `IN_PROGRESS → IN_REVIEW → TESTING → VERIFIED → COMPLETED`. You may move a task to `VERIFIED` only if its required tests ran green in your session. Do not skip rungs. If a test fails, the task goes back to `IN_PROGRESS` with the failure noted.
8. Update the §A progress counts and §F quality gates in the same change.
9. If you change a canonical name/enum/endpoint/event/table, update [AGENTS.md §0](AGENTS.md) and every referencing document in the same commit (AGENTS.md §F rule 14).
10. Never edit another agent's `IN_PROGRESS` row except to add a blocker comment.

Evidence cell format: `` `<command>` → <result>; <artifact path>; <date> ``

---

## E. Execution History (newest first)

| Date | Agent | Task | Changes | Verification | Outcome | Follow-up |
|---|---|---|---|---|---|---|
| 2026-10-30 | Claude (Sonnet 5.5) | Blueprint (pre-backlog) | Authored `AGENTS.md`, `PLAN.md`, `ARCHITECTURE.md`, `PROGRESS-TRACKER.md`, `UI-REGISTRY.md` at repo root. Read PS-001 from the supplied PDF. | **Documentation only.** A script checked that backlog task IDs are unique, every dependency exists and the graph is acyclic (85 tasks). Cross-document name checks: see §F. **No code, no tests, no build was run — none exist.** | Documents created | Start T0.01. Resolve BL-1…BL-3. Review DD-1…DD-9. |

### Evaluation scenario results (filled only from real runs; `—` = not run)

| Scenario | Last run | Result | Repeats | Run log path | Notes |
|---|---|---|---|---|---|
| SC-1 Feature | — | NOT RUN | — | — | — |
| SC-2 Seeded bug | — | NOT RUN | — | — | — |
| SC-3 Failing-test recovery | — | NOT RUN | — | — | — |
| SC-4 Security | — | NOT RUN | — | — | — |
| SC-5 Unavailable tool | — | NOT RUN | — | — | — |
| SC-6 Ambiguity | — | NOT RUN | — | — | — |
| SC-7 Repeated failure/escalation | — | NOT RUN | — | — | — |

---

## F. Quality Gates

| Gate | Command / source | Status | Last run | Evidence |
|---|---|---|---|---|
| Build — backend | `python -m compileall backend/app` | NOT RUN (no code) | — | — |
| Build — frontend | `npm run build` (frontend/) | NOT RUN (no code) | — | — |
| Lint | `make check` (ruff, eslint) | NOT RUN | — | — |
| Type check | `mypy --strict`, `tsc --noEmit` | NOT RUN | — | — |
| Unit tests | `pytest backend/tests/unit` | NOT RUN | — | — |
| Integration tests | `pytest backend/tests/integration` | NOT RUN | — | — |
| Sandbox escape suite | `pytest backend/tests/integration/test_sandbox_escape.py` | NOT RUN | — | — |
| Security checks (secret scan of repo) | `gitleaks detect` or `sec.scan_secrets` | NOT RUN | — | — |
| Eval scenarios | `python -m eval.run --all` | NOT RUN | — | — |
| Acceptance verification (verifier) | verifier reports on SC runs | NOT RUN | — | — |
| UI smoke + axe | `npx playwright test` | NOT RUN | — | — |
| Approval flow | approval API tests + E2E | NOT RUN | — | — |
| Document consistency | names/enums/events/tasks cross-check (see script note) | PARTIAL — checked at authoring (2026-10-30) | 2026-10-30 | Authoring-time script; re-run when docs change |

---

## G. Submission Checklist (PS-001 deliverables)

Check an item only with evidence (path or link). All currently unchecked.

- [ ] Source code and working demonstration — evidence:
- [ ] Multi-agent architecture with defined roles (AGENTS.md §B, README) — evidence:
- [ ] Working implementation → testing → verification workflow — evidence:
- [ ] ≥ 1 end-to-end mission with run log showing a feedback loop (R-DEMO) — evidence: `runs/…`
- [ ] Setup instructions, configuration files, list of supported tools — evidence: README, `.env.example`
- [ ] README: architecture diagram + agent responsibilities
- [ ] README: communication, orchestration, shared-state design
- [ ] README: setup + configuration
- [ ] README: available tools and execution boundaries
- [ ] README: human approval mechanism, security assumptions, known limitations
- [ ] All reported results come from actual runs; verified vs. assumed separated (R-TRUTH) — evidence: report partition
- [ ] Scenarios SC-1…SC-7 run and recorded (honest failures included)
- [ ] Bonus (optional, only if actually implemented and tested): parallel agents (B-1) · auto rerun/self-correction (B-2) · memory or single-agent baseline (B-3)
- [ ] Demo fallback prepared and labelled (recorded / scripted / live)

---

## H. Accuracy Rules

- Do not fabricate completed work. A row is `COMPLETED` only if its Evidence cell lets someone else reproduce the verification.
- At initial generation every unimplemented task is `NOT_STARTED` (or `READY` if dependency-free). **No task here has implementation evidence.**
- Keep four states separate in all reporting: **planned** (in PLAN.md) · **implemented** (code exists) · **tested** (tests executed, results recorded) · **verified** (acceptance criteria demonstrated, evidence attached).
- Model claims, agent self-reports and "should work" statements are never evidence.
- A skipped or unavailable test is reported as `SKIPPED`/`NOT RUN`, never `PASSED`.

## Implementation status (updated after the first build session)

Verified by actually running: `pytest` 115 passed, `ruff` clean, `tsc`/`eslint` clean, `next build` OK, plus a headless-browser pass of the full demo flow (create → run → approve → report; 375px and 1440px).

| Area | Status | Evidence / caveat |
|---|---|---|
| Phase 0–1 (schemas, DB, API, SSE, state manager, LLM layer) | VERIFIED | tests; SQLite only, no Alembic, no `users` table |
| Phase 2 tools, policy, path jail, scanners, tamper detector | VERIFIED | 50+ policy cases, jail/escape tests. **T2.04 Docker runner NOT STARTED**; local-jail only |
| Phase 3 LangGraph, master, watchdog, planner, interrupts | VERIFIED | e2e SC-3. **T3.08 replan path implemented but untested** |
| Phase 4–5 developer/tester/security, critique loop, EXECUTE re-run | VERIFIED (scripted model) | live-model behaviour UNTESTED; T5.06 parallel devs, T5.07 memory NOT STARTED |
| Phase 6 verifier process, gate, approval, report, rollback | VERIFIED | isolation + sabotage tests |
| GitHub import + branch/commit/push/PR | VERIFIED for clone/branch/push against a local bare remote; PR API + real github.com NOT TESTED | token via env header (unit-tested) |
| Phase 7 frontend | IMPLEMENTED + browser-checked | no Monaco (custom unified diff), no replay/Playwright tests committed |
| Phase 8 scenarios | PARTIAL | only SC-3 fixture + test; SC-1/2/4/5/6/7 fixtures and harness NOT STARTED |
| T9.* | README written; compose/demo recording NOT STARTED |

Bugs found by running (all have regression tests): stale `.pyc` after same-size edits (compileall), git `index.lock` race between parallel tester/security, symlinked data dir crash, relative data dir breaking `--junitxml`, `/etc` import guard bypass on macOS, developer self-checks counted as gate evidence.
Deviations from the blueprint: master uses a deterministic policy (LLM optional, guarded); tester/security are tool-driven without an LLM by design; `forced_by` gained `POLICY`; gate allows INCONCLUSIVE (manual-review) criteria only with explicit human acknowledgement.
