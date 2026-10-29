# 03 — Agents: Roles, Contracts, Prompts

Every agent is an instance of the same `AgentRunner` loop (see §9) parameterised by:
`role`, `system_prompt`, `allowed_tools`, `submit_tool` (output contract), `model`, `budget`.

## 0. Permissions matrix (enforced by the Tool Gateway, not by prompts)

| Tool ↓ / Agent → | Shogun | Scout | Samurai | Sentinel | Verifier | Reviewer | Security |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `fs.list` / `fs.read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `search.code` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `fs.edit` / `fs.write` (workspace) | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `fs.write_probe` (probes dir only) | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `test.run` | ❌ | ✅¹ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `shell.run` (allowlisted) | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| `git.diff` / `git.status` / `git.log` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `scan.secrets` / `scan.static` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `memory.recall` | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `board.read` | ✅ | ✅ | ✅ | ✅ | ❌² | ✅ | ✅ |
| `msg.send` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `human.ask` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

¹ Scout runs the test suite once to confirm the detected test command.
² Verifier gets a **filtered** view (spec + ACs + RepoBrief + diff) — never Samurai's reasoning.

---

## 1. 🏯 Shogun — Strategist & Commander

**Purpose:** Turn the request into a mission spec, build and revise the plan, and make bounded decisions at every decision point.

**Invoked in modes:** `analyze`, `plan`, `replan`, `decide`, `adjudicate` (disputes).

**Inputs:** request, `RepoBrief`, memory recalls, blackboard snapshot, decision context (triggering event + evidence summaries).

**Outputs (submit tools):**
- `submit_mission_spec(MissionSpec)`
- `submit_plan(Plan)`
- `submit_decision(Decision)`

**Behavioural rules (system prompt excerpt):**
```
You are the Shogun. You do not write code. You command.
- Every acceptance criterion MUST be objectively checkable and name a verification_method
  (existing_test | new_test | probe | static_check | manual).
- If the request admits ≥2 materially different interpretations, set ambiguity.level="high"
  and propose ONE clarifying question with 2-4 concrete options. Otherwise state your assumption.
- Preserve existing behaviour unless the request says otherwise: always include an AC
  "All pre-existing tests that passed at baseline still pass."
- When deciding, cite evidence IDs. Never decide based on an agent's claim alone.
- Prefer the cheapest action that changes the outcome. Retrying the same thing with no new
  information is forbidden; if the failure fingerprint repeated, choose INVESTIGATE, REASSIGN or REPLAN.
```

---

## 2. 🔭 Scout — Reconnaissance

**Purpose:** Map the codebase so others act in context. Also re-invoked as an **investigator** when the Shogun chooses `INVESTIGATE`.

**Algorithm:**
1. Deterministic pre-pass (no LLM): file tree (depth 3, ignore `.git`, `node_modules`, `.venv`), detect language/test framework (`pyproject.toml`, `pytest.ini`, `setup.cfg`, `package.json`), detect linters (`ruff`, `flake8`, `eslint`), git log -5.
2. LLM pass: read key files, search for symbols from the request, infer conventions.
3. Run detected test command once → baseline evidence.
4. `submit_repo_brief(RepoBrief)`.

```python
class Convention(BaseModel):
    aspect: Literal["naming","formatting","typing","docstrings","errors","structure","testing","imports"]
    observation: str            # "functions are snake_case; private helpers prefixed _"
    example_ref: str            # "src/cart.py:L12-L20"

class RelevantFile(BaseModel):
    path: str
    reason: str
    symbols: list[str] = []

class RepoBrief(BaseModel):
    languages: list[str]
    test_command: list[str]      # argv, e.g. ["python","-m","pytest","-q"]
    lint_command: list[str] | None
    baseline_evidence_id: str    # E-xxxx from the baseline test run
    baseline_summary: str        # "14 passed, 1 failed (test_dates.py::test_leap)"
    entrypoints: list[str]
    conventions: list[Convention]
    relevant_files: list[RelevantFile]
    risks: list[str]             # "no tests cover discount rounding", "global state in config.py"
    notes: str = ""
```

---

## 3. ⚔️ Samurai — Developer (dynamically spawned)

**Purpose:** Implement one task in the workspace following conventions. One Samurai per task; parallel when tasks don't share files.

**Inputs:** `Task`, `RepoBrief`, relevant memory, any `TriageReport` / `ReviewFinding` / `VerifierVerdict` routed to this task, prior `ChangeReport` (on rework), **attempt history with failure fingerprints**.

**Rules (system prompt excerpt):**
```
You are a Samurai. You implement exactly the task assigned, nothing more.
- Read before you write. Locate the code with search.code, read surrounding context, then edit.
- Prefer fs.edit (exact string replacement) over fs.write; keep diffs minimal.
- Match conventions in the RepoBrief (naming, typing, docstrings, error handling).
- Add or update tests for the behaviour you change, in the project's existing test style.
- Do NOT modify pre-existing test assertions unless the task explicitly allows it
  (task.may_edit_tests == true). If you believe a test is wrong, send a DISPUTE with evidence.
- Run the relevant tests yourself before submitting.
- If an attempt failed before with fingerprint F, you MUST state a different hypothesis.
- If you are blocked (missing info, tool unavailable, conflicting requirement), submit
  status="blocked" with what you need. Do not guess silently.
```

```python
class ChangeReport(BaseModel):
    task_id: str
    attempt: int
    status: Literal["done","blocked","partial"]
    hypothesis: str               # what I believed was needed / root cause
    approach: str                 # what I did and why
    files_changed: list[str]
    tests_added: list[str]
    self_check_evidence_ids: list[str]   # tests I ran (may be empty → flagged)
    claims: list[str]             # e.g. "handles negative quantities" (UNVERIFIED until checked)
    blockers: list[str] = []
    disputes: list[str] = []      # message IDs of disputes raised
```

---

## 4. 🛡️ Sentinel — Test Runner & Failure Triage

**Purpose:** Own the truth about tests. Runs suites, parses results, and when something fails, investigates *why* and routes a precise finding to the responsible Samurai.

**Algorithm:**
1. `test.run` full suite (structured: JUnit XML via `--junitxml`).
2. Compare to baseline: classify each test as `still_passing`, `newly_passing`, `newly_failing` (**regression**), `still_failing`, `new_test`.
3. For each failure: read traceback, read implicated source lines, optionally re-run the single test with `-x -vv`, compute **failure fingerprint** (see `04` §6).
4. `submit_test_report(TestReport)` (+ embedded `TriageReport` per failure).

```python
class TestCaseResult(BaseModel):
    nodeid: str
    outcome: Literal["passed","failed","error","skipped"]
    baseline_outcome: Literal["passed","failed","error","skipped","absent"]
    classification: Literal["still_passing","newly_passing","regression","still_failing","new_test_pass","new_test_fail"]
    message: str | None = None

class Triage(BaseModel):
    nodeid: str
    fingerprint: str              # sha1 of normalised error
    error_type: str               # "AssertionError", "ImportError", ...
    root_cause_hypothesis: str
    implicated_locations: list[str]   # "src/pager.py:L41"
    suggested_fix: str            # concrete but not code-dump
    confidence: Literal["low","medium","high"]
    likely_owner_task: str | None
    is_environmental: bool        # missing dep, flaky, timeout → not a code bug

class TestReport(BaseModel):
    evidence_id: str
    command: list[str]
    exit_code: int
    totals: dict[str, int]        # passed/failed/error/skipped
    cases: list[TestCaseResult]
    regressions: list[str]
    triage: list[Triage]
    verdict: Literal["green","red","error"]
```

---

## 5. ⚖️ Verifier — Independent Acceptance Checker

**Purpose:** Answer one question per acceptance criterion: *is there execution evidence that this is satisfied?* Operates with **information hiding** (ADR-005).

**Algorithm (per AC):**
1. Read the AC + diff + relevant code.
2. If `verification_method` names an existing/new test → locate it, confirm it actually exercises the AC (not a tautology), run it.
3. Else write a **probe test** in `runs/<id>/probes/test_probe_<ac>.py` that imports from the workspace, covering the AC plus 1-2 edge cases the AC implies; run it.
4. Verdict per AC: `PASS` (evidence exit 0), `FAIL` (evidence exit≠0 with explanation), `INCONCLUSIVE` (could not construct a check → goes to human).

```python
class ACVerdict(BaseModel):
    ac_id: str
    verdict: Literal["PASS","FAIL","INCONCLUSIVE"]
    evidence_ids: list[str]
    reasoning: str
    probe_paths: list[str] = []
    counterexample: str | None = None   # concrete input → observed vs expected

class VerifierVerdict(BaseModel):
    diff_sha: str                 # verdict is bound to this exact diff
    per_ac: list[ACVerdict]
    overall: Literal["ACCEPT","REJECT","INCONCLUSIVE"]
```

> The verdict is bound to `diff_sha`. Any later code change invalidates it and forces re-verification (guard in the orchestrator).

---

## 6. 🕵️ Reviewer — Code Review

**Purpose:** Review the diff for correctness, readability, consistency with `RepoBrief.conventions`, regressions, test quality, and scope creep.

**Checklist injected into prompt:**
- Correctness: edge cases (empty, None, boundaries, negative), error paths.
- Consistency: naming, typing, docstrings, structure match the repo.
- Tests: do new tests assert behaviour (not implementation)? Were existing tests weakened?
- Scope: changes unrelated to the request?
- Regressions: callers of modified functions (use `search.code` to find them).

```python
class ReviewFinding(BaseModel):
    id: str
    severity: Literal["blocker","major","minor","nit"]
    category: Literal["correctness","consistency","readability","tests","scope","regression","performance"]
    location: str                 # "src/cart.py:L33"
    description: str
    suggestion: str
    evidence_ids: list[str] = []  # e.g. a search result showing an unhandled caller

class ReviewReport(BaseModel):
    diff_sha: str
    decision: Literal["approve","request_changes"]
    findings: list[ReviewFinding]
```
`request_changes` iff any `blocker` or `major` finding.

---

## 7. 🥷 Security Inspector

**Purpose:** Basic security inspection of the **diff and touched files** (and a full-repo secret scan once per mission).

**Pipeline:**
1. `scan.secrets` (built-in regex + entropy) on diff and repo.
2. `scan.static` → `bandit -f json` on touched Python files (if installed; else fallback rule set).
3. LLM review of diff + scanner output for: SQL/command/path injection, `eval`/`exec`, `pickle` on untrusted data, `subprocess(shell=True)`, `yaml.load` without SafeLoader, disabled TLS verification, hardcoded credentials, unsafe file permissions, path traversal.
4. Distinguish **introduced** (in diff) vs **pre-existing** issues. Introduced high/critical → blocker. Pre-existing → reported; fixed only if in scope or human approves scope expansion.

```python
class SecurityFinding(BaseModel):
    id: str
    severity: Literal["critical","high","medium","low","info"]
    cwe: str | None               # "CWE-89"
    source: Literal["scan.secrets","bandit","semgrep","fallback_rules","llm"]
    introduced_by_change: bool
    location: str
    description: str
    remediation: str
    evidence_ids: list[str]

class SecurityReport(BaseModel):
    diff_sha: str
    decision: Literal["pass","block"]
    findings: list[SecurityFinding]
    scanners_run: list[str]
    scanners_unavailable: list[str]   # transparency about degraded mode
```

---

## 8. Inter-agent interaction patterns (why this is not "sequential personas")

| Pattern | Example | Mechanism |
|---|---|---|
| **Consume another's result** | Samurai reads Scout's `RepoBrief.conventions`; Verifier reads Sentinel's test evidence | Blackboard records |
| **Directed feedback** | Sentinel → Samurai: "T2 regression: `test_page_count` fails, fingerprint `a91f…`, cause: `ceil` replaced with `//`" | `msg.send(to=samurai:T2, type=FINDING)` |
| **Request / response** | Samurai → Scout: "Where is `RATE_LIMIT` configured?" | `REQUEST` / `RESPONSE`; orchestrator spawns a Scout investigation |
| **Critique & dispute** | Reviewer flags `blocker`; Samurai disputes with a passing probe | `DISPUTE` → Shogun `adjudicate` |
| **Plan revision from findings** | Scout investigation reveals 2nd module needs change → Shogun `REPLAN` adds T3 | `PLAN_REVISED` |
| **Escalation** | Same fingerprint 3× → Shogun → Human | `ESCALATION` |

---

## 9. The agent loop (shared by all agents)

```python
async def run_agent(spec: AgentSpec, ctx: AgentContext) -> BaseModel:
    messages = [user_msg(render_briefing(spec, ctx))]
    tools = registry.schemas_for(spec.role) + [spec.submit_tool.schema]
    for step in range(spec.budget.max_steps):                    # default 25
        ctx.budget.check()                                       # tokens / wall clock → raises BudgetExceeded
        resp = await llm.create(model=spec.model, system=spec.system_prompt,
                                messages=messages, tools=tools, max_tokens=4096)
        bus.emit(AgentThought(agent=ctx.agent_id, text=resp.text_blocks))   # transparency
        if not resp.tool_uses:
            messages += [assistant(resp), user_msg("Continue. Finish by calling "
                                                  f"{spec.submit_tool.name}.")]
            continue
        results = []
        for tu in resp.tool_uses:
            if tu.name == spec.submit_tool.name:
                out = spec.submit_tool.validate(tu.input)        # pydantic; error → returned to model
                if out.ok:
                    return out.value
                results.append(tool_error(tu.id, out.error)); continue
            results.append(await gateway.execute(ctx.agent_id, spec.role, tu))   # policy + evidence
        messages += [assistant(resp), user_msg(results)]
        messages = compact_if_needed(messages)                   # summarise old tool outputs
    raise StepBudgetExceeded(ctx.agent_id)
```

Tool errors (denied, timeout, unavailable) are **returned to the model as tool results** with a structured reason and suggested alternatives — this is how agents adapt to failed tools.
