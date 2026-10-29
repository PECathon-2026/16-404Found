# 01 — Problem Analysis (First Principles)

> PS-001 — **DevPilot: The Mystic Mikado's Autonomous AI Engineering Guild**
> Turn a natural-language software request into a **working, tested, reviewed** change to an existing small repository, using a multi-agent system that **coordinates, adapts, and proves its work with evidence.**

---

## 1. What the judges are actually buying

Reading the PS literally, then reading between the lines:

| Surface ask | What it really tests | Our answer in one line |
|---|---|---|
| "Multi-agent system" | That agents **change each other's behaviour** — not a chain of personas | Typed message bus + shared blackboard; agents act on each other's findings, and we log *why* the next action was chosen |
| "Plan / Build / Test / Review" | Separation of concerns **with independent checks** | Verifier and Reviewers run in **fresh contexts**, never see the developer's self-report |
| "Adapt until the mission is complete" | Feedback loops that **change strategy**, not just retry | Failure fingerprinting: same error twice → forced strategy change; three times → escalate |
| "Must not claim success without evidence" | Honesty / anti-hallucination | **Evidence Ledger**: every claim cites an evidence ID produced by a real tool run; the report generator — not an LLM — decides what is "VERIFIED" |
| "Restrict commands, block destructive ops" | Responsible autonomy | Tool Gateway: path jail, command allowlist, no `shell=True`, scrubbed env, git worktree isolation |
| "Human approval before consequential actions" | Human-in-the-loop design | Mandatory **Apply Gate**; optional plan gate; escalation channel |
| "Not a fixed pipeline of chatbots" | The control flow must be **data-dependent** | Event-driven orchestrator: the next step is a function of evidence, chosen from a bounded action set |
| "Transparency" | Can a human inspect plan, decisions, tools, tests | Append-only event log → live CLI view + HTML mission report |
| Bonus: parallel / dynamic agents | Real concurrency | Dynamic Samurai spawn per independent task; Review ∥ Security ∥ Verify run in parallel |
| Bonus: persistent memory, single-agent baseline | Scientific rigour | SQLite memory of repo conventions/lessons; `--mode single` baseline graded by **hidden held-out tests** |

**Thesis:** We win on *trustworthiness*, not agent count. The demo must show a human a run where (1) a real test failed, (2) an agent read that evidence and did something *different*, (3) an independent checker caught something the developer missed, and (4) the final report separates verified facts from model claims.

---

## 2. Decomposing the requirements

### 2.1 Requirement Traceability Matrix

Every requirement in the PS maps to a component and a demo proof point. This table is the checklist judges will implicitly run.

| ID | PS Requirement | Component(s) | Proof in demo / artifact |
|---|---|---|---|
| A1 | Requirement analysis → objectives + acceptance criteria | Shogun `analyze` phase → `MissionSpec` | `mission.json` → `acceptance_criteria[]` each with `verification_method` |
| A2 | Codebase reconnaissance | Scout agent → `RepoBrief` | `repo_brief.json` (conventions, test cmd, relevant files, risks) |
| A3 | Task decomposition, delegation, **revision** | Shogun `plan`/`replan` → `Plan v1..vN` | Plan version history in report; `PLAN_REVISED` events with reason |
| A4 | Shared mission state | Blackboard (event-sourced) | `events.jsonl`, `state.sqlite`, live board view |
| B1 | ≥3 tools, agent chooses | Tool registry (15 tools) | Tool-call timeline with agent rationale |
| B2 | Context-aware dev, follow style | `RepoBrief.conventions` + memory injected; `fs.edit` is str-replace (minimal diffs) | Reviewer "consistency" check passes; small diffs |
| B3 | Adaptive problem solving | Fingerprint-driven strategy change | `STRATEGY_CHANGED` event in run log |
| B4 | Controlled execution | Tool Gateway policy | `POLICY_DENIED` events; sandbox tests |
| C1 | Automated testing | Sentinel + `test.run` (structured JUnit parse) | `test_run` evidence records |
| C2 | Failure investigation & repair, send back, rerun | Sentinel `TriageReport` → message to Samurai | Feedback loop in run log |
| C3 | Independent verification | Verifier (fresh context, probe tests) | `VerifierVerdict` per acceptance criterion |
| C4 | Evidence-based completion | Evidence Ledger + deterministic report renderer | `REPORT.md` with VERIFIED / FAILED / UNRESOLVED / CLAIMS sections |
| D1 | Code review | Reviewer agent | `ReviewReport` findings |
| D2 | Security inspection | Security Inspector (scanners + LLM) | `SecurityReport`, planted-vuln fixture caught |
| D3 | Cross-agent critique, disputes by evidence or human | Dispute protocol | `DISPUTE` / `DISPUTE_RESOLVED` / `ESCALATED` events |
| D4 | Human approval for consequential actions | Human Gate (Apply mandatory) | Approval prompt in demo; `HUMAN_DECISION` event |
| E1 | Inter-agent communication (not sequential personas) | Message bus with addressed messages + subscriptions | Messages reference other agents' evidence IDs |
| E2 | Feedback loops trigger investigation | Event → policy → action | Demo loop |
| E3 | Adaptive orchestration: continue/retry/clarify/stop | Shogun decision policy (bounded action enum) | `DECISION` events with justification |
| E4 | Bounded autonomy | `Budgets`, iteration limits, circuit breakers, permissions matrix | Chaos fixture → clean escalation, no infinite loop |
| T | Evaluation scenarios ×5 | Fixture repos + eval harness | `eval/results.md` table |
| Del | README, setup, config, tool list, run log | Docs suite + `runs/<id>/` | This repo |
| Bonus | Parallel/dynamic agents, self-correction, memory, baseline | Spawner, Sentinel loop, MemoryStore, `--mode single` | Eval comparison table |

### 2.2 Implicit requirements (not written, but will be judged)

1. **Determinism for the demo.** LLMs are stochastic; a live demo can fail. → We record LLM responses ("cassettes") and support `--replay` so the demo is reproducible, while still running **real** tools/tests (tool outputs are never replayed).
2. **Cost/latency.** A 6-agent system can burn tokens. → Per-mission token budget, cheaper model for high-volume agents, output truncation.
3. **The target repo must never be damaged.** → All work happens in a git worktree; the original is touched only on human approval.
4. **Graders will try to break it.** → Ambiguous request, missing tool, impossible test — each must end in a *graceful, explained* state.
5. **Judges skim.** → A one-screen final report and a 3-minute demo script.

---

## 3. First-principles design constraints

Derived from "what makes an autonomous coding change trustworthy?":

1. **Separation of authorship and judgement.** The agent that writes code must not be the one that declares it correct. → Samurai writes; Sentinel runs; Verifier judges with independent context.
2. **Truth comes from execution, not from text.** → Only tool outputs create evidence. LLM text creates *claims*.
3. **Loops need a convergence argument.** Every loop has (a) a progress signal (failure fingerprint changes / fewer failing tests), (b) a hard cap, (c) an exit to a human.
4. **Least privilege per role.** Scout and Verifier can't edit source; Reviewer can't run arbitrary commands; nobody can push, delete, or reach the network.
5. **State is shared, ownership is not.** Everyone reads the blackboard; only the owner of a record type writes it (Shogun owns the plan, Sentinel owns test evidence, etc.).
6. **Control flow is code; judgement is LLM.** The orchestrator's state machine and guards are deterministic Python; the LLM chooses *among allowed actions* at decision points. This gives adaptivity without unbounded behaviour.

---

## 4. Scope decisions (what we will NOT build)

| Out of scope | Why |
|---|---|
| GitHub PRs, remote push | PS says local repo is enough; push is a consequential/network action |
| Arbitrary languages | Primary support: **Python (pytest)**. Secondary: **Node (npm test)** detection only. Fixtures are Python. |
| Large repos / RAG over embeddings | "Small repository" — ripgrep + file tree is sufficient and more transparent |
| Containers / VMs | Worktree + policy gateway is enough for a hackathon; Docker documented as a future hardening step |
| Fancy web app | Rich CLI live view + static HTML report gives 90% of transparency at 10% of the cost |

---

## 5. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Live LLM flakiness during demo | High | High | Cassette replay; pre-recorded backup video |
| Agents loop forever | Medium | High | Budgets + fingerprint escalation + global wall clock |
| Agent edits tests to make them pass | Medium | High | Test-file protection: edits to existing test files require explicit plan permission and are flagged by Reviewer; Verifier uses hidden probe tests |
| Rate limits | Medium | Medium | Concurrency semaphore (default 3 parallel LLM calls), exponential backoff |
| Windows/Unix path differences | Medium | Medium | `pathlib` everywhere; CI on both; no shell strings |
| Over-engineering in 36h | High | High | Phased plan with a "walking skeleton" by H8 (see `09-IMPLEMENTATION-PLAN.md`) |
