# UI-REGISTRY.md — DevPilot Interface System

> Canon names/enums/events: [AGENTS.md §0](AGENTS.md#0-canonical-names-the-single-naming-authority) · Endpoints & event payloads: [ARCHITECTURE.md §E](ARCHITECTURE.md) · Tasks: `T7.*` in [PROGRESS-TRACKER.md](PROGRESS-TRACKER.md) · Plan: [PLAN.md Phase 7](PLAN.md)
> Stack: Next.js (App Router) · TypeScript strict · Tailwind CSS · shadcn/ui · Lucide · React Flow (`reactflow`/`@xyflow/react`) · Monaco (`@monaco-editor/react`) · TanStack Query (REST cache) · Zustand (event-sourced mission store) · EventSource (SSE).
> Status: **design specification; no UI code exists** (see tracker).

---

## A. Design Philosophy

A modern AI engineering command center — dense like Linear, restrained like Vercel, workflow-literate like GitHub, observability-first like agent tracing dashboards. Not a clone of any product.

1. **Dark-first**, with a full light theme (tokens, not separate styles). Respect `prefers-color-scheme`; user override in Settings.
2. **Evidence on screen.** Every number, status, log line, diff, and finding is rendered from backend state (§I traceability rule). If data is missing, show an explicit "no data" state — never a placeholder value.
3. **Functional, not decorative.** Color encodes status/severity only. Motion explains state change (≤ 200 ms) or is absent.
4. **Information hierarchy:** mission status & required human action first → what's happening now → evidence → history.
5. **Not a chatbot.** The central surface is a structured activity/evidence feed with typed items (decisions, messages, tool calls, findings), not a chat transcript.
6. **Accessible & responsive:** WCAG 2.1 AA contrast, full keyboard operation, focus rings, ARIA live regions for status, `prefers-reduced-motion` honored, usable ≥ 360 px wide (workspace degrades to tabs).
7. **Honest mode banners:** show when the sandbox is `local_jail` (weaker), when a run is `replay` or `scripted` (not live), when a criterion is `LLM_JUDGED`.

---

## B. Design Tokens

Implemented in `frontend/src/styles/tokens.css` as CSS variables, mapped in `tailwind.config.ts`. Hex values are design proposals; validate contrast with an automated check (T7.13) before locking.

### B.1 Color (dark default; light in parentheses)

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg-canvas` | `#0B0D10` | `#FFFFFF` | App background |
| `--bg-surface` | `#12151A` | `#F7F8FA` | Panels, cards |
| `--bg-elevated` | `#181C22` | `#FFFFFF` | Popovers, dialogs |
| `--bg-hover` | `#1E232B` | `#EEF0F3` | Row/button hover |
| `--border-subtle` | `#232830` | `#E4E7EC` | Dividers |
| `--border-strong` | `#323945` | `#CBD0D8` | Inputs, focus-adjacent |
| `--text-primary` | `#E8EAED` | `#14171C` | Body |
| `--text-secondary` | `#A3AAB5` | `#4A5160` | Labels |
| `--text-muted` | `#6E7685` | `#6B7280` | Meta (≥ 4.5:1 on surface only for ≥ 14 px; verify) |
| `--accent` | `#6E8BFF` | `#3B5BDB` | Primary action, focus ring, links |
| `--accent-fg` | `#0B0D10` | `#FFFFFF` | Text on accent |

**Semantic status** (always paired with an icon and text label — never color alone):

| Token | Dark | Meaning |
|---|---|---|
| `--status-running` | `#5AA9FF` | IN_PROGRESS, agent thinking/tool |
| `--status-success` | `#3FB68B` | DONE, PASS, GREEN, RESOLVED, COMPLETED |
| `--status-warning` | `#E3A23B` | MEDIUM, AWAITING_HUMAN, PAUSED, retry |
| `--status-danger` | `#E5534B` | FAILED, FAIL, RED, HIGH/CRITICAL |
| `--status-critical` | `#FF6B9A` | CRITICAL (distinct from HIGH by hue + icon `ShieldAlert`) |
| `--status-neutral` | `#7B8494` | PENDING, UNVERIFIED, INFO, CANCELLED |
| `--status-approval` | `#B48CFF` | AWAITING_APPROVAL (action required from user) |

**Agent identity colors** (accents on avatars/graph nodes only; each agent also has a fixed Lucide icon and text name): `master #E3B341 Crown` · `planner #6E8BFF Compass` · `developer #3FB68B Hammer` · `tester #5AD1D9 FlaskConical` · `security #E5534B ShieldCheck` · `verifier #B48CFF BadgeCheck`.

**Diff colors:** add `rgba(63,182,139,.14)` / remove `rgba(229,83,75,.14)` backgrounds; Monaco theme `devpilot-dark`/`devpilot-light`.

### B.2 Typography
- UI: **Inter** (system-ui fallback). Mono: **JetBrains Mono** (ui-monospace fallback) for ids, hashes, commands, terminal, diffs.
- Scale (px/line-height): `xs 12/16` · `sm 13/20` · `base 14/22` · `md 16/24` · `lg 18/28` · `xl 22/30` · `2xl 28/36`. Weights 400/500/600. Tabular numerals (`font-variant-numeric: tabular-nums`) for metrics.
- Ids shown as `mis_01JB…K2D` (head + tail) with copy-on-click and full value in `title`/tooltip.

### B.3 Spacing, radii, elevation, borders
- Spacing: 4 px base — `1=4, 2=8, 3=12, 4=16, 5=20, 6=24, 8=32, 10=40, 12=48`. Default panel padding 16; dense rows 8×12.
- Radii: `sm 4` (badges, inputs) · `md 6` (buttons, cards) · `lg 10` (dialogs, panels) · `full` (avatars, dots).
- Elevation: flat by default (borders, not shadows). `--shadow-popover: 0 8px 24px rgba(0,0,0,.35)`; `--shadow-dialog: 0 16px 48px rgba(0,0,0,.5)`. No glow effects.
- Borders: 1 px `--border-subtle`; focus ring 2 px `--accent` with 2 px offset (never removed).

### B.4 Motion
`--dur-fast 100ms` (hover) · `--dur-base 160ms` (panel/popover) · `--dur-slow 240ms` (dialog, graph edge pulse). Easing `cubic-bezier(.2,.8,.2,1)`. A pulsing dot (1.2 s) indicates a *live* running agent only. All animation disabled under `prefers-reduced-motion` (replace pulse with static ring).

### B.5 Breakpoints
`sm 640` · `md 768` · `lg 1024` · `xl 1280` · `2xl 1536`. Layout modes: **< 768** single column + bottom tab bar; **768–1279** collapsible sidebar + two-pane workspace; **≥ 1280** three-pane workspace.

---

## C. Application Navigation

Sidebar (`Sidebar`, collapsible to icons; mobile: bottom `TabBar`). Routes use App Router under `frontend/src/app/`.

| Item | Route | Icon | Purpose |
|---|---|---|---|
| Overview | `/` | `LayoutDashboard` | Active missions needing attention, recent outcomes, aggregate metrics (real data) |
| Missions | `/missions` | `ListChecks` | Searchable/filterable list; "New mission" |
| Mission Workspace | `/missions/[missionId]` | `Workflow` | The primary working surface (deep-linked, tab state in URL) |
| Agent Network | `/agents` (global) and workspace tab "Network" | `Network` | Live agent topology for a selected mission (global page picks a mission; defaults to the most recent running) |
| Repositories | `/repositories` | `GitBranch` | Imported repos, detected commands, recent missions |
| Execution History | `/history` | `History` | Past missions, filter by outcome, open **ExecutionReplay** |
| Reports | `/reports` | `FileText` | Final reports (verified/unresolved/model-claims), patch download |
| Settings | `/settings` | `Settings` | Providers & model routing, budgets, sandbox mode, permissions defaults, theme |

Global elements: top bar with breadcrumb, command palette (`Cmd/Ctrl+K`: jump to mission, create mission, toggle theme), attention indicator (count of missions in `AWAITING_HUMAN` / `AWAITING_APPROVAL`), sandbox-mode chip.

---

## D. Mission Workspace (`/missions/[missionId]`)

### D.1 Layout (≥ 1280 px)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ MissionHeader: title · MissionStatusBadge · repo@base_commit · mode chips · actions     │
│ ProgressBar (tasks DONE/total · criteria PASS/total) · BudgetMeter · ActiveAgents strip │
├───────────────┬──────────────────────────────────────────────┬─────────────────────────┤
│ LEFT (320)    │ CENTER (flex)  Tabs                          │ RIGHT (360)             │
│ CriteriaList  │ Activity | Diff | Tests | Security | Graph   │ ApprovalPanel (sticky)  │
│ TaskList /    │ | Network | Timeline | Report                │ HumanRequestCard        │
│ TaskDepGraph  │                                              │ AgentCard list (6)      │
│ (toggle)      │                                              │ MetricsPanel (compact)  │
└───────────────┴──────────────────────────────────────────────┴─────────────────────────┘
```
- 768–1279: left column collapses into a drawer; right panel becomes a collapsible bottom sheet that auto-expands on `approval.requested`/`human.input_requested`.
- < 768: header compacts; tabs become a scrollable segmented control; ApprovalPanel is a full-width sticky card at top when action is required.

### D.2 Regions

| Region | Components | Data source |
|---|---|---|
| Mission header | `MissionStatusBadge`, repo chip, `ModeChips` (sandbox mode, replay/scripted, network on) , actions (Start/Pause/Resume/Cancel) | `GET /missions/{id}`, events `mission.status_changed` |
| Progress | `ProgressBar` (derived: tasks DONE÷non-superseded; criteria PASS÷total) | tasks, acceptance_criteria |
| Active agents | `AgentCard` compact ×6 | `MissionDetail.agents`, `agent.started/finished`, `tool.called` |
| Task graph | `TaskDependencyGraph` | `GET /tasks`, `task.*` events |
| Execution timeline | `MissionTimeline` | `decision.made`, `mission.status_changed`, `repair.initiated`, `verification.*`, `approval.*` |
| Communication feed | `AgentActivityFeed` (+ `ToolExecutionCard`, `TerminalOutput`) | `message.sent`, `critique.*`, `tool.*`, `decision.made` |
| Code diff | `CodeDiffViewer` | `GET /diffs`, `file.modified` |
| Test results | `TestResultPanel` | `GET /test-runs`, `test.*` |
| Security findings | `SecurityFindingCard` list | `GET /findings`, `finding.*` |
| Approval | `ApprovalDialog` via `ApprovalPanel` | `approval.requested`, gate reasons, `GET /verification` |
| Report | `EvidencePartition` (verified / unresolved / model claims) | `GET /report` |

---

## E. Agent Network (`AgentNetworkGraph`)

Interactive React Flow canvas (P1, T7.10); falls back to a static list (`AgentCard` grid) if disabled or on small screens.

- **Nodes (6):** `master` (center), `planner`, `developer`, `tester`, `security`, `verifier` (drawn with a dashed "isolated process" border and a lock icon). Node content: icon, display name, status chip (`idle | thinking | tool | waiting | failed`), current task key, last tool, retry count badge.
- **Edges:** derived from `message.sent` (sender→recipient). Solid = control (`TASK_ASSIGN`, `TASK_RESULT`); dashed = peer critique (`CRITIQUE`, `CRITIQUE_RESPONSE`, `QUESTION`). An edge pulses for 1.2 s on a new message (static highlight under reduced motion). Edge label = message type; thickness = message count (capped).
- **Feedback loops:** a cycle highlight when a `repair.initiated` event links tester→developer→tester (loop counter badge "repair ×2").
- **Failed operations:** nodes with a failed `agent_execution` or `tool.failed` within the last 30 s show a danger ring + count; click opens the failing `ToolExecutionCard`.
- **Task ownership:** hovering a node highlights its tasks in `TaskDependencyGraph`; clicking filters `AgentActivityFeed` to that agent.
- **Controls:** zoom/pan, fit view, minimap off by default, filter by message type, "follow active" toggle. Layout is fixed (hub-and-spoke) — positions deterministic so screenshots are stable.
- **Data:** edges/nodes computed from the store's event log (same reducer as replay). No synthetic traffic.

---

## F. Component Registry

Location root: `frontend/src/components/` (shared UI) and `frontend/src/features/<feature>/` (feature-bound). Common conventions: every data component accepts `missionId`, reads from `useMissionStore` selectors (never fetches inside leaf components except via TanStack hooks in `features/*/api.ts`), exposes `data-testid` equal to its name, and renders four states — **loading** (skeleton matching layout), **empty** (`EmptyState` with next action), **error** (inline error card + retry, never a blank), **ready**.

For brevity: *A11y* lists component-specific requirements on top of the global ones (focus visible, semantic roles, contrast, keyboard operability, `aria-live="polite"` for status changes, reduced motion).

### F.1 AppShell — `components/layout/AppShell.tsx`
- **Purpose:** frame: Sidebar, top bar, content outlet, command palette, attention indicator, toasts.
- **Props:** `children`, `attention?: {awaitingHuman: number; awaitingApproval: number}`.
- **Data:** `GET /missions?status=AWAITING_HUMAN,AWAITING_APPROVAL` (poll 30 s + SSE global attention via per-mission streams of open missions), `GET /config/models` (sandbox mode chip).
- **States:** loading (shell renders immediately; chip skeleton) / error (banner "Cannot reach backend" with retry; app remains navigable).
- **Interactions:** collapse sidebar, `Cmd/Ctrl+K`, theme toggle.
- **A11y:** landmarks `header`, `nav`, `main`; skip-to-content link.
- **Responsive:** ≥ 1024 sidebar; < 768 bottom TabBar.

### F.2 Sidebar — `components/layout/Sidebar.tsx`
- **Purpose:** primary navigation (§C). **Props:** `items`, `collapsed`, `onToggle`, `activePath`. **Data:** static + attention counts. **States:** collapsed/expanded/active; counts hidden at zero. **Interactions:** click, arrow-key navigation, tooltip when collapsed. **A11y:** `nav` with `aria-current="page"`. **Responsive:** becomes TabBar < 768.

### F.3 MissionCard — `features/missions/MissionCard.tsx`
- **Purpose:** list row/card summarizing a mission. **Props:** `mission: MissionSummary` (`id,title,status,repository.name,updated_at,counters,budgets,pending_action?`), `density: "row"|"card"`.
- **Data:** `GET /missions`. **States:** loading skeleton; `pending_action` highlight (approval/human).
- **Interactions:** click → workspace; kebab: cancel/pause (confirm). **A11y:** entire card is a single link with accessible name "title, status"; kebab is a separate button. **Responsive:** row ≥ 768, card < 768.

### F.4 MissionStatusBadge — `features/missions/MissionStatusBadge.tsx`
- **Purpose:** canonical rendering of `MissionStatus`. **Props:** `status`, `reason?`, `size`.
- **Mapping:** CREATED neutral/`Circle` · PLANNING running/`Compass` · EXECUTING running/`Loader` (static icon under reduced motion) · VERIFYING running/`BadgeCheck` · AWAITING_HUMAN warning/`MessageCircleQuestion` · AWAITING_APPROVAL approval/`GitPullRequest` · PAUSED warning/`Pause` · COMPLETED success/`CheckCircle2` · REJECTED danger/`XCircle` · FAILED danger/`AlertOctagon` · CANCELLED neutral/`Ban`.
- **A11y:** text label always visible; `role="status"` when live. Tooltip shows `reason`.

### F.5 AgentCard — `features/agents/AgentCard.tsx`
- **Purpose:** one agent's live state. **Props:** `agentId`, `status`, `currentTask?`, `lastTool?`, `executions`, `tokens`, `costUsd`, `compact?`.
- **Data:** `MissionDetail.agents`, `agent.*`, `tool.*`, `/metrics/missions/{id}`.
- **States:** idle / thinking / tool / waiting / failed (danger border + reason). Verifier card shows "isolated process" tag.
- **Interactions:** click filters feed to agent; expand shows last 5 tool calls. **A11y:** `aria-live` off for compact (avoid noise); status in text. **Responsive:** compact strip in header on < 1280.

### F.6 AgentNetworkGraph — `features/agents/AgentNetworkGraph.tsx`
- **Purpose:** §E. **Props:** `missionId`, `followActive?`, `onSelectAgent`. **Data:** event log from store (`message.sent`, `agent.*`, `tool.failed`, `repair.initiated`, `critique.*`).
- **States:** empty (no messages yet: nodes shown idle, caption "No agent messages yet"); error → fallback list. **Interactions:** pan/zoom, node click, edge click → open message in feed.
- **A11y:** graph has a text alternative: a visually-hidden table of agents/edges; nodes focusable (Tab), Enter selects; legend with icons. **Responsive:** < 768 shows `AgentCard` list instead.

### F.7 TaskDependencyGraph — `features/tasks/TaskDependencyGraph.tsx`
- **Purpose:** DAG of tasks. **Props:** `tasks`, `dependencies`, `selectedTaskId?`, `onSelect`, `layout: "dag"|"list"`.
- **Data:** `GET /tasks`; `task.created/status_changed/superseded`. Uses React Flow with dagre layout (left→right). SUPERSEDED tasks render faded with strike-through key; retry count badge; kind icon.
- **States:** empty ("Plan not created yet"), loading, error. **Interactions:** select → highlights criteria refs & filters feed; toggle list view. **A11y:** list view is the accessible default for screen readers; graph nodes have `aria-label` "TASK-3 Implement…, IN_PROGRESS, depends on TASK-1". **Responsive:** list-only < 768.

### F.8 AgentActivityFeed — `features/activity/AgentActivityFeed.tsx`
- **Purpose:** chronological typed feed (decisions, messages, critiques, tool calls, file modifications, test results, findings). **Props:** `missionId`, `filters {agent?, type?, task?, severity?}`, `follow: boolean`.
- **Data:** store event log + `GET /messages`, `/decisions`, `/logs` for backfill (cursor).
- **Item kinds:** `DecisionItem` (action chip, rationale, evidence refs, `forced_by` tag) · `MessageItem` (sender→recipient, type, severity, summary, thread by `correlation_id`) · `CritiqueItem` (finding link, ACCEPT/DISPUTE state) · `ToolExecutionCard` · `FileModifiedItem` · `TestItem` · `FindingItem` · `SystemItem` (policy.denied, budget.warning).
- **States:** loading, empty ("Waiting for the first agent step"), error. **Interactions:** filter chips, thread collapse, "jump to latest", click evidence ref → opens target (tool call, test run, diff hunk). Virtualized list (`@tanstack/react-virtual`). **A11y:** `role="log"` `aria-live="polite"` for appended items (rate-limited announcements: batched); each item is an `article` with heading. **Responsive:** full width; metadata wraps.

### F.9 ToolExecutionCard — `features/activity/ToolExecutionCard.tsx`
- **Purpose:** one tool call with args summary, status, duration, exit code, excerpt. **Props:** `toolCall: {id, agent_id, tool, args_summary, status, exit_code?, duration_ms?, output_excerpt?, output_ref?, policy_reason?, redactions}`.
- **States:** RUNNING (spinner + elapsed time from `started_at`, real clock), OK, ERROR, DENIED (shows policy reason), TIMEOUT. "N secrets redacted" chip if `redactions > 0`.
- **Interactions:** expand → `TerminalOutput` loading full output on demand (`GET /tool-calls/{id}`); copy command; copy id. **A11y:** expandable via button with `aria-expanded`. **Responsive:** args wrap; output scrolls horizontally.

### F.10 TerminalOutput — `components/code/TerminalOutput.tsx`
- **Purpose:** render real captured stdout/stderr. **Props:** `text`, `stream: "stdout"|"stderr"|"mixed"`, `truncated`, `fullOutputUrl?`, `maxHeight`.
- **Behavior:** monospace, ANSI color → tokens, line numbers, search (`/`), stderr tinted. **Never** shows simulated output: if the tool is RUNNING and no bytes yet, show "No output yet". If truncated, show "Truncated — view full output" (link). **States:** loading/empty/error. **A11y:** `role="region" aria-label="Command output"`, text selectable, copy button. **Responsive:** horizontal scroll, no wrapping by default (toggle).

### F.11 CodeDiffViewer — `features/diff/CodeDiffViewer.tsx`
- **Purpose:** inspect the mission patch. **Props:** `missionId`, `patchSha?` (default current), `mode: "split"|"unified"`, `onSelectFile`.
- **Data:** `GET /diffs`; `file.modified` refreshes (debounced). Monaco `DiffEditor` (lazy-loaded). File tree with change-type icons and +/− counts; test-file tag; **tamper flag banner** ("Existing test modified") on `tamper_flags`.
- **States:** loading (skeleton tree + editor placeholder), empty ("No changes yet"), error (fallback to plain unified text from `GET /patch`). **Interactions:** switch file, split/unified, jump to hunk from finding/test failure, download patch, compare with previous checkpoint (`patch=<sha>`). **A11y:** Monaco accessibility mode on; file list is keyboard navigable; hunk navigation shortcuts (`F7`/`Shift+F7`). **Responsive:** unified-only < 1024.

### F.12 TestResultPanel — `features/tests/TestResultPanel.tsx`
- **Purpose:** baseline vs. latest runs, failures, regressions, lint/build. **Props:** `missionId`.
- **Data:** `GET /test-runs`; `test.run_started/passed/failed`. Layout: run timeline (BASELINE, then each run with `patch_sha256` short + outcome), summary tiles (total/pass/fail/skipped from the run), failure list (test id, `FailureClass` chip, message, `suspected_files`, `caused_by_patch` tag), "regressions vs baseline" list. **UNAVAILABLE** runs (e.g. `ENV_MISSING_TOOL`) render as a warning "Not executed", never as pass.
- **Interactions:** select run, open raw output (TerminalOutput), jump to file in diff, show repair link ("repair initiated from this run"). **A11y:** results in a table with headers; status text not color-only. **Responsive:** table → stacked rows.

### F.12b MetricsPanel — `features/metrics/MetricsPanel.tsx`
- **Purpose:** AGENTS §G metrics for this mission or overall. **Props:** `scope: {missionId} | "all"`, `compact?`. **Data:** `GET /metrics/missions/{id}` / `/metrics/summary`. Shows tokens, cost vs. ceiling, iterations, repair cycles, tool calls/redundant rate, message counts, latency per agent. **States:** metrics lacking data show "no data" (never 0 as filler). **A11y:** each tile has label + value + unit; charts have table alternatives. **Responsive:** 2-col grid → 1-col.

### F.13 SecurityFindingCard — `features/security/SecurityFindingCard.tsx`
- **Purpose:** one finding with evidence and lifecycle. **Props:** `finding: Finding`, `onWaive?`, `onOpenInDiff`.
- **Data:** `GET /findings`; `finding.created/resolved`; critique thread via `correlation_id`.
- **States:** OPEN, FIX_PROPOSED, RESOLVED, DISPUTED (shows both sides + evidence), WAIVED_BY_HUMAN (reason + who), WONT_FIX_EVIDENCED. Severity chip (INFO…CRITICAL; icon + text), category/CWE, `file:line`, evidence excerpt (masked secrets), recommendation, confidence ("scanner-confirmed" vs "model-suspected").
- **Interactions:** open in diff, view scanner tool call, waive (HIGH/CRITICAL requires reason; confirm dialog). **A11y:** severity conveyed in text; waive dialog traps focus. **Responsive:** card stack.

### F.14 ApprovalDialog — `features/approval/ApprovalDialog.tsx` (+ `ApprovalPanel.tsx`)
- **Purpose:** the human gate. **Props:** `missionId`, `open`, `onClose`.
- **Data:** `GET /verification`, `/diffs`, `/findings`, `/test-runs`, `/report`; gate reasons from `approval.requested`; **`patch_sha256`** pinned at open.
- **Content:** (1) verdict header: gate clear/blocked; (2) per-criterion table `AC-n | method | status | evidence`, LLM-judged rows marked "model claim"; (3) test summary baseline→final; (4) findings (open/resolved/waived); (5) diff summary with files + test-file/tamper flags; (6) unresolved items & degraded evidence notes; (7) decision: **Approve**, **Request changes** (comment required), **Reject**.
- **States:** gate blocked → Approve disabled with reasons listed; stale (`patch_sha256` changed via SSE) → banner "Patch changed — review again" and decisions disabled until refreshed; submitting; error (409 shown verbatim).
- **A11y:** modal dialog with focus trap, `aria-describedby` summary, keyboard-only completion tested, destructive actions require confirmation. **Responsive:** full-screen sheet < 768.

### F.14b HumanRequestCard — `features/approval/HumanRequestCard.tsx`
- **Purpose:** clarification/escalation (`human.input_requested`). **Props:** `request: {id, kind, question, options[], evidence_refs[]}`. Shows the specific question, proposed default, options as buttons plus free-text; evidence links (e.g., the repeated failing runs). Submit → `POST /respond`. **States:** open/answered/expired. **A11y:** `role="alertdialog"` if blocking; focus moves to the card on arrival (without stealing focus from active typing — announce via live region instead).

### F.15 MissionTimeline — `features/timeline/MissionTimeline.tsx`
- **Purpose:** high-level story of the mission. **Props:** `missionId`.
- **Data:** milestone events: status changes, master decisions, repair cycles, verification, approval. Vertical timeline with elapsed time since start, grouped by lifecycle phase; repair loops shown as nested "Repair cycle n" groups (failure class → attempt → rerun result).
- **States:** loading/empty/error. **Interactions:** click scrolls feed to the item; filter "decisions only". **A11y:** ordered list; each entry has timestamp + text. **Responsive:** single column.

### F.16 MissionCreationWizard — `features/missions/MissionCreationWizard.tsx`
- **Purpose:** create a mission in 4 steps: **Repository** → **Mission** (prompt + optional criteria hints) → **Permissions & limits** → **Review**.
- **Props:** `onCreated(missionId)`, `initialRepositoryId?`. **Data:** `GET /repositories`, `POST /repositories`, `GET /config/models`, `POST /missions`, `POST /missions/{id}/start` (optional "Start immediately").
- **Defaults:** network off, install deps off, limits per ARCH §B.8; warnings if sandbox mode is `local_jail`. Review step lists exactly what will be allowed.
- **States:** validation errors inline; submit loading; backend error preserved with retry; draft persisted to `sessionStorage`. **A11y:** step list with `aria-current="step"`, errors linked via `aria-describedby`, Enter-to-advance, Esc to close with unsaved warning. **Responsive:** dialog ≥ 768 / full page < 768.

### F.17 RepositorySelector — `features/repositories/RepositorySelector.tsx`
- **Purpose:** pick or import a repo. **Props:** `value`, `onChange`, `allowImport`. **Data:** `GET /repositories`; import form (`local path` / `git URL`) → `POST /repositories`; shows detected language, `head_commit`, detected commands (after import analysis). **States:** empty ("Import your first repository"), importing, import error (path not found / not a repo / excluded secrets list shown). **A11y:** combobox pattern. **Responsive:** list in popover/sheet.

### F.18 ModelSelector — `features/settings/ModelSelector.tsx`
- **Purpose:** choose model/routing per role. **Props:** `value: ModelConfig`, `onChange`, `catalog`. **Data:** `GET /config/models` (ids, tiers, capabilities, provider availability — never keys). Modes: "Auto (router)" default, or per-role override with capability warnings (e.g. model lacks tool support → disabled). Shows cost tier badge from configured prices (or "price not configured"). **States:** provider unavailable (disabled with reason). **A11y:** listbox with descriptions.

### F.19 ExecutionReplay — `features/replay/ExecutionReplay.tsx`
- **Purpose:** replay a finished mission (X-4). **Props:** `missionId`. **Data:** `GET /replay` (ordered events) fed through the **same reducer** as live SSE; controls: play/pause, speed (1×/4×/16×), step, scrub (event index), jump to next failure/decision. A persistent banner "Replay — not live". **States:** loading (progress), empty (no events), error. **A11y:** transport buttons labelled; scrubber is a slider with value text "Event 112 of 340"; no autoplay. **Responsive:** controls bottom-docked.

### F.20 EmptyState — `components/feedback/EmptyState.tsx`
- **Purpose:** consistent empty messaging. **Props:** `icon`, `title`, `description`, `action?{label,onClick|href}`. Must name the next real action (e.g. "Create mission"). No illustrations beyond a Lucide icon. **A11y:** heading level via prop.

### F.21 ErrorBoundary — `components/feedback/ErrorBoundary.tsx`
- **Purpose:** isolate render failures per region (feed, diff, graph) so one crash doesn't blank the workspace. **Props:** `fallback?`, `onError?`, `resetKeys?`. Shows error summary + "Retry" + "Copy details" (error id, component, mission id; no secrets). Reports to console/logger endpoint. **A11y:** `role="alert"`.

### F.22 Supporting components (also registered)
| Name | File | Purpose / key props |
|---|---|---|
| `CriteriaList` | `features/criteria/CriteriaList.tsx` | `AC-n` list with `CriterionStatus`, verification method chip, `LLM_JUDGED` marker, evidence links; updates on `verification.completed`. |
| `ModeChips` | `components/layout/ModeChips.tsx` | Sandbox mode (`docker`/`local_jail`), `live`/`replay`/`scripted`, network on/off. Data from `MissionDetail.config` + server mode. |
| `BudgetMeter` | `features/metrics/BudgetMeter.tsx` | Tokens/cost/wall-clock used vs. limit from `budgets`; warning color at ≥ 80 % (`budget.warning`). |
| `ProgressBar` | `components/ui/ProgressBar.tsx` | Derived progress with text alternative "5 of 8 tasks done". |
| `EvidencePartition` | `features/report/EvidencePartition.tsx` | Verified / Unresolved / Unverified agent claims / Model claims columns from `outcome`. |
| `EvidenceRef` | `components/evidence/EvidenceRef.tsx` | Clickable chip for `{kind,id,locator}`; resolves to tool call, test run, finding, diff hunk, decision. |
| `AttentionBanner` | `components/feedback/AttentionBanner.tsx` | "Action required: approval / answer" with jump button. |

---

## G. Page Specifications

State management (all pages): **TanStack Query** for REST resources (cache keys `["mission", id, resource]`); **Zustand `useMissionStore`** holds the *event-sourced* live state per open mission: `applyEvent(evt)` is a pure reducer used by both the SSE hook and Replay. On connect: fetch snapshots (REST) → subscribe to SSE with `Last-Event-ID` = last applied event id → reducer applies deltas; on reconnect resume from last id; on gap/`409` refetch snapshot. SSE hook: exponential backoff 1→15 s, pauses when tab hidden > 60 s (resumes with Last-Event-ID).

### G.1 Overview `/`
- **Layout:** AttentionBanner → grid: "Needs your attention" (MissionCards with pending actions) · "Running now" · "Recent outcomes" · `MetricsPanel scope="all"`.
- **APIs:** `GET /missions` (+filters), `GET /metrics/summary`.
- **States:** empty → `EmptyState` "No missions yet — create your first mission" (opens wizard). Loading skeleton grid. Error card with retry. Metrics tiles show "no data" when absent.
- **Responsive:** 3-col → 2-col → 1-col.

### G.2 Missions `/missions`
- **Layout:** toolbar (search, status filter, repository filter, "New mission") → list of `MissionCard density=row` (virtualized when > 100) → cursor pagination.
- **APIs:** `GET /missions`, `POST /missions` via wizard.
- **States:** empty/filtered-empty; loading; error. Status counts from response.
- **Interactions:** keyboard `j/k` to move, `Enter` open.

### G.3 Mission Workspace `/missions/[missionId]`
- **Layout:** §D. Tab state in query string (`?tab=diff&file=...`).
- **APIs:** `GET /missions/{id}`, `/tasks`, `/messages`, `/decisions`, `/logs`, `/diffs`, `/test-runs`, `/findings`, `/verification`, `/report`, control endpoints, `POST /approvals`, `/respond`, SSE `/events`.
- **Interactions:** Start/Pause/Resume/Cancel with confirm; Approve flow; waive finding; open evidence refs across tabs; follow-live toggle.
- **States:** loading (skeleton layout); 404 ("Mission not found" + back); SSE disconnected chip ("Reconnecting… last event 12 s ago", data marked stale, not removed); terminal missions show final `EvidencePartition` and Replay button; `AWAITING_*` shows sticky action card.
- **Responsive:** §D.1.

### G.4 Agent Network `/agents`
- **Layout:** mission picker (default: latest running) → `AgentNetworkGraph` (large) + side panel (selected agent: AgentCard expanded, recent messages, current task) + legend.
- **APIs:** same event store as workspace (shares the SSE connection by `missionId`).
- **States:** no missions → EmptyState; no running → shows the latest finished mission with "Replay" option.

### G.5 Repositories `/repositories`
- **Layout:** table (name, source, language, head, detected commands, last mission outcome) + import panel (`RepositorySelector` import mode). **APIs:** `GET/POST /repositories`. **States:** empty/importing/error (explicit reasons). Responsive: table → cards.

### G.6 Execution History `/history`
- **Layout:** filterable table of terminal missions (outcome, duration, repair cycles, cost, criteria pass count) → row opens workspace (read-only) with **ExecutionReplay**. **APIs:** `GET /missions?status=COMPLETED,FAILED,REJECTED,CANCELLED`, `/replay`.
- **States:** empty ("No finished missions yet"), loading, error.

### G.7 Reports `/reports`
- **Layout:** list of reports → report view: summary, `EvidencePartition`, criteria table, test baseline→final, findings with resolutions, approvals, budget, download patch/report (`/patch`, `/report?format=md`). **APIs:** `GET /report`, `/patch`. **States:** missions without report yet are hidden; empty/error.

### G.8 Settings `/settings`
- **Layout:** sections — Providers (status only, no key display; keys are set via backend env), Model routing (`ModelSelector` defaults per role), Limits defaults, Sandbox (mode, network default, command profile visibility read-only), Appearance (theme), Data retention (read-only info). **APIs:** `GET /config/models`; mutable settings (limits/theme) persisted locally or via `PUT /config` if added (not in MVP: **read-only config + local theme**). **States:** provider unavailable shown with reason.

---

## H. Real-Time Experience

Transport: SSE `GET /api/v1/missions/{id}/events` (framing in ARCHITECTURE §E.4). One `EventSource` per open mission, owned by `useMissionEvents(missionId)`; events are appended to the store's log and reduced into derived state. Reaction to events must be **idempotent** (same event id applied twice has no effect).

| Event (canonical) | Store effect | UI response |
|---|---|---|
| `mission.created` | create mission record | Appears at top of `/missions` and Overview; wizard navigates to workspace. |
| `task.created` / `task.status_changed` / `task.superseded` | add/update task; superseded → faded | `TaskDependencyGraph` node added/recolored/struck through; progress bar recomputed; feed `SystemItem` for replans ("Plan revised: 3 tasks superseded"). |
| `message.sent` | append message, update edge counters | Feed `MessageItem` (grouped by `correlation_id`); network edge pulse + count; unread dot on Activity tab when not focused. |
| `agent.finished` | agent status → idle or failed | `AgentCard` ring stops; failed → danger state with error; execution tokens/cost refresh. |
| `human.input_received` | clear pending request | `HumanRequestCard` collapses to "Answered"; `AttentionBanner` removed; status badge follows `mission.status_changed`. |
| `policy.denied` | append audit item | Feed `SystemItem` with tool + policy reason (args redacted); counts toward the agent's "denied" badge. |
| `agent.started` | `agents[agent_id].status="thinking"`, current execution | `AgentCard` shows running ring + task key; network node status chip; feed `SystemItem` (collapsed). |
| `task.delegated` | task assignee/status → IN_PROGRESS | Task graph node updates owner badge; feed `MessageItem` (TASK_ASSIGN) ; network edge master→agent pulses. |
| `tool.called` | add tool call RUNNING | `ToolExecutionCard` appears with live elapsed timer; AgentCard `lastTool`; status → `tool`. |
| `tool.completed` / `tool.failed` | update call status/exit/duration | Card flips to OK/ERROR; failed → agent node danger ring (30 s), feed highlights; TerminalOutput available. |
| `file.modified` | add to patch file list, `current_patch_sha256` | Diff tab badge increments; `CodeDiffViewer` refetches `/diffs` (debounced 500 ms); feed `FileModifiedItem` with +/−; tamper flag banner if present. |
| `test.run_started` | add run RUNNING | Tests tab spinner; timeline entry. |
| `test.failed` | run outcome RED; failures added | `TestResultPanel` shows failures with `FailureClass`; Tests tab badge (danger); timeline "Test failed"; toast only if user is on another tab. |
| `repair.initiated` | create/mark REPAIR task; increment cycles; link to failing run | Timeline opens "Repair cycle n" group; network loop highlight + counter; feed `DecisionItem` with `strategy_changed` tag; task graph shows REPAIR node. |
| `test.passed` | run GREEN | Success state; progress updated; repair group closed with "Resolved". |
| `critique.raised` / `critique.resolved` | add critique thread | Feed `CritiqueItem` with ACCEPT/DISPUTE; dashed network edge pulse; link to finding. |
| `finding.created` / `finding.resolved` | add/update finding | Security tab badge by max severity; `SecurityFindingCard`; CRITICAL/HIGH raises `AttentionBanner` ("blocks approval"); resolved → success state with resolving patch hash. |
| `decision.made` | add decision | Timeline + feed `DecisionItem` (action chip, rationale, evidence refs, `forced_by`). |
| `verification.started` | verifier node status | Verifier card "isolated run"; Criteria rows show "verifying…". |
| `verification.completed` | store report; update criteria statuses | `CriteriaList` rows PASS/FAIL/INCONCLUSIVE; LLM-judged rows tagged; if overall≠PASS feed highlights why master re-opened work. |
| `human.input_requested` | set pending request | `HumanRequestCard` (right panel/top sheet), `AttentionBanner`, browser notification if permitted, status badge AWAITING_HUMAN. |
| `approval.requested` | set pending approval with gate info | Sticky `ApprovalPanel`, auto-open `ApprovalDialog` only when the workspace tab is focused (otherwise banner + title badge); AWAITING_APPROVAL badge. |
| `approval.resolved` | record approval | Dialog closes; status updates; APPROVED → final `EvidencePartition` appears. |
| `budget.warning` | budget flag | `BudgetMeter` warning color + toast once per resource per threshold. |
| `mission.status_changed` | status | `MissionStatusBadge` update (`aria-live`), header actions enabled/disabled per status. |
| `mission.completed` / `mission.failed` | terminal | Stop live indicators, close SSE after final event, show Report tab, offer Replay; failure shows reason + unresolved items. |

Connection semantics: on connection loss show "Reconnecting…" and mark data stale (reduced opacity on live indicators; nothing is deleted); on resume apply missed events; if the server signals a gap, refetch snapshots and rebuild. A "Live / Reconnecting / Replay / Scripted" chip is always visible.

---

## I. UI Quality Standards

**Avoid:** heavy gradients; decorative blur/glow; looping animation without state meaning; chat-bubble layouts; fake terminal/typing effects; hardcoded or random metrics; placeholder numbers; decorative components without function; status communicated by color only; modal stacking; auto-scrolling that fights user scroll.

**Traceability rule (enforced in review):** every rendered data value maps to an API field or reduced event. Each component's spec above names its data source; PR descriptions for `T7.*` must include a table `UI element → API field/event`. Where backend data is absent, render "no data". Mock data is allowed **only** in Storybook/tests and must be labelled `fixture` in the fixture file name; production bundles must not import fixtures (lint rule `no-restricted-imports` on `**/fixtures/**`).

**Quality checklist per component (T7.13):**
- [ ] Four states implemented (loading/empty/error/ready)
- [ ] Keyboard-only operable; visible focus; logical tab order
- [ ] axe: 0 serious/critical violations
- [ ] Contrast ≥ 4.5:1 text / 3:1 UI in both themes
- [ ] 375 px, 768 px, 1440 px screenshots from a real replayed mission attached as evidence
- [ ] Reduced-motion verified
- [ ] No secrets in rendered output (redaction chip shows when applied)
- [ ] Idempotent event handling verified (duplicate event test)

**Performance budgets:** initial workspace render < 2 s on fixture mission (1,000 events); feed virtualized; Monaco and React Flow lazy-loaded; event batching with `requestAnimationFrame` (apply ≤ 50 events per frame).

**Testing:** component tests (Vitest + Testing Library) driven by recorded event streams from real runs (`frontend/tests/fixtures/*.jsonl`, named `fixture-*`); Playwright smoke on a replayed mission: open workspace → see failing test → repair → approve; axe in CI.

---

## J. Cross-References

- Event names ↔ [AGENTS.md §0.6](AGENTS.md) ↔ [ARCHITECTURE.md §E.4](ARCHITECTURE.md).
- Status enums ↔ [AGENTS.md §0.3](AGENTS.md). Never redefine labels; import from `frontend/src/lib/enums.ts` generated from the backend canonical list (T0.05 enum-parity test also checks the generated TS file).
- Task IDs: T7.01–T7.13 in [PROGRESS-TRACKER.md](PROGRESS-TRACKER.md).
- Agent names/colors: §B.1 here; canonical ids in AGENTS §0.2.


---

## Cosmic Command Center redesign (implemented; supersedes the visual tokens in §B for the running app)

Verified by running: `tsc` and `eslint` clean on all new/changed files, `next build` passes (14 routes), and a headless-browser pass of the full flow at 1600px and 375px (palette, terminal search, run-log import/replay, a full mission to the approval step). No component renders fabricated data.

| Component | File | Data source |
|---|---|---|
| Design tokens, glass surfaces, starfield, orbit/planet/pulse keyframes | `app/globals.css` | n/a (honours `prefers-reduced-motion`; light theme keeps tokens, hides the starfield) |
| Command-bar header, ⌘K palette, nav (11 routes), current-mission block + Stop Mission | `components/AppShell.tsx`, `components/Palette.tsx` | missions, repositories, `/missions/{id}/cancel` |
| Orbital **AgentGuild** | `features/cosmic/AgentGuild.tsx` | `MissionDetail.agents` (status), `message.sent` (pulses), `tool.failed`/`policy.denied` (failure ring), `repair_cycles` (retry badge). Idle = "standby"/"idle", never animated as working |
| MissionFlow (7 stages + evidence) | `features/cosmic/MissionFlow.tsx`, `lib/derive.ts` | tasks, test runs, findings, verification, events |
| Active mission + controls (pause/resume/cancel/approve/reject-with-reason) | `features/cosmic/ActiveMissionPanel.tsx` | mission detail; reuses `ApprovalPanel` |
| Repository explorer, file view | `features/cosmic/RepoExplorer.tsx`, `DevPanels.tsx` | `GET /missions/{id}/files`, `/files/content` (jailed + redacted) |
| Per-test results, read-only terminal | `features/cosmic/DevPanels.tsx` | `GET /test-runs/{id}/cases` (junit artifact), tool-call log |
| Metric cards | `features/cosmic/MetricCards.tsx` | derived from missions; sparkline only with >= 3 missions; "no data" otherwise |
| Run-log import + replay (from `frontend2`) | `features/cosmic/ImportRunLog.tsx`, `lib/runlog.ts` | local file, DevPilot + legacy JSONL; always labelled "Replay: not live" |
| New pages | `app/terminal`, `app/tests`, `app/security` | live mission views with a mission picker |

Agent display names: planner = **Shogun**, developer = **Samurai**, tester = **Sentinel**, security = **Shadow**, master = **DevPilot Orchestrator**, verifier = **Verifier** (isolated process). Presentation only; ids are unchanged.

Ideas taken from `frontend2/` (a standalone React-18 prototype with hard-coded sample data): constellation view, command palette, run-log upload + replay with speed, expandable event details, terminal search, reject-with-reason, attempts, evidence report. Its sample data and its separate event format were NOT carried over; an adapter reads its format into real events.

Not done / limitations: no Monaco or xterm.js (a custom unified diff and a read-only log; the sandbox allowlist forbids a writable terminal); no coverage (shown as "not collected"); no "Run Tests" or chat-with-agents controls (the backend has no such endpoint); user avatar/name is local-only (no accounts); the Deployment stage is shown as "Human approval" because DevPilot applies a patch rather than deploying.
