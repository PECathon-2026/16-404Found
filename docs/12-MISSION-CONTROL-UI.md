# 12 — Mission Control UI & API

The UI is a first-class product surface: it is how judges experience *transparency*, *coordination* and *human oversight*. It supersedes ADR-010 (CLI-first). The CLI remains for scripting and evaluation.

## 1. Stack (decided)

| Concern | Choice |
|---|---|
| App | **Vite + React 18 + TypeScript (strict)** SPA in `web/`, served by FastAPI in production (`/` static) |
| Styling | **Tailwind CSS v3 + shadcn/ui** (Radix primitives), `lucide-react` icons, `framer-motion` |
| Graphs | **@xyflow/react** (React Flow): Guild Graph and Plan DAG; `elkjs` for auto layout |
| Code | **@monaco-editor/react**: diff editor with decorations for findings |
| Data | **Zustand** (live mission store) + **TanStack Query** (REST) |
| Lists | **react-virtuoso** (event timeline with 10k+ events) |
| Charts | **Recharts** (budget, eval dashboards), custom SVG for the trace waterfall |
| Command palette | **cmdk** (`⌘K`: jump to task / AC / evidence / event) |
| Markdown | `react-markdown` + `remark-gfm` + `rehype-highlight` |
| Types | Generated from pydantic: `scripts/gen_types.py` → JSON Schema → `json-schema-to-typescript` → `web/src/types/generated.ts`. **Never hand-write API types.** |
| Tests | Vitest + Testing Library; Playwright smoke test against a recorded mission |

## 2. Backend API (FastAPI, `devpilot/api/`)

### REST
| Method | Path | Body / Query | Returns |
|---|---|---|---|
| POST | `/api/missions` | `{repo_path, request, mode: "multi"\|"single", profile: "fast"\|"balanced"\|"careful", replay_cassette?, chaos?}` | `{id}` (mission starts asynchronously) |
| GET | `/api/missions` | | `MissionSummary[]` |
| GET | `/api/missions/{id}` | `?at_seq=` (time travel) | `Mission` |
| GET | `/api/missions/{id}/events` | `?from_seq=&to_seq=&types=` | `Event[]` |
| GET | `/api/missions/{id}/diff` | `?ref=main&against=baseline&at_seq=` | `{files: [{path, old, new, hunks}]}` |
| GET | `/api/missions/{id}/files` | `?ref=&path=&at_seq=` | file content |
| GET | `/api/missions/{id}/evidence/{eid}` | | `Evidence` + `raw` (truncated to 1 MB) |
| GET | `/api/missions/{id}/trace` | | `Span[]` |
| POST | `/api/missions/{id}/prompts/{pid}/answer` | `{choice?, free_text?}` | `HumanDecision` |
| POST | `/api/missions/{id}/abort` · `/resume` | | status |
| GET | `/api/missions/{id}/report` | `?format=md\|html\|json` | report |
| GET | `/api/modes` | | Mode Registry (id, agent, tier, tools, slices, hidden, limits, output JSON schema) |
| GET | `/api/fixtures` | | fixture list from `fixtures/*/scenario.toml` |
| GET | `/api/eval/results` | | eval results JSON |
| GET | `/api/config` | | resolved config (models per tier, budgets) with secrets removed |

### WebSocket `/ws/missions/{id}?from_seq=N`
Server → client frames:
```ts
type Frame =
  | { kind: "hello"; mission_id: string; last_seq: number; snapshot: Mission }      // on connect
  | { kind: "event"; event: Event }                                              // every event incl. ephemeral deltas
  | { kind: "patch"; seq: number; ops: JsonPatchOp[] }                          // RFC 6902 patch of Mission after event seq
  | { kind: "heartbeat"; ts: string };
```
- The server keeps the last serialized `Mission` per subscriber and sends **JSON Patch** diffs (`jsonpatch` lib) after each persisted event. The UI applies them with `fast-json-patch`. The UI **never re-implements projection logic**.
- On reconnect: the client sends `from_seq = lastSeenSeq + 1`. If the gap is larger than 500 events, the server sends a fresh `hello`.
- Client → server: `{kind:"answer", prompt_id, choice?, free_text?}` (same as REST) and `{kind:"ping"}`.

## 3. Information architecture

```
/                      Launchpad
/m/:id                 Mission Control  (default tab: Guild)
/m/:id/report          Mission Report (print-friendly)
/eval                  Evaluation dashboard (multi vs single)
/modes                 Mode Registry explorer
```

## 4. Mission Control layout

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ⛩ DevPilot  M-…-7c1d  "Users report the last page…"   ● EXECUTING   ⏱ 03:12  💰 $1.84/15      │
│ INTEL ─ RECON ─ ANALYZE ─ PLAN ─ ACCEPT ─ [EXECUTE] ─ TEST ─ CHECK ─ APPLY ─ REPORT           │
│ tokens ▓▓▓▓░░░ 31%   cycles ▓▓░░░░ 2/8   time ▓▓░░░ 11%            [⌘K] [Pause] [Abort]       │
├───────────────┬──────────────────────────────────────────────────────────────┬────────────────┤
│ PLAN v2  ↺    │ [Guild] [Timeline] [Trace] [Diff] [Tests] [Tournament] [Memory]│ INSPECTOR      │
│ ● T1 DONE     │                                                              │                │
│ ◐ T2 REWORK 2 │        ┌────────┐   FINDING F-3   ┌─────────┐                │ samurai#2      │
│ ○ T3 PENDING  │        │Sentinel│ ───────────────▶ │Samurai#2│ (pulsing)      │ mode: rework   │
│               │        └────────┘                  └─────────┘               │ model: sonnet  │
│ ACCEPTANCE    │   ┌──────┐      ┌──────┐   ┌────────┐  ┌────────┐            │ thinking 10k   │
│ AC-1 ✅ 0.93  │   │Shogun│◀─────│Scout │   │Verifier│  │Reviewer│            │ context: spec, │
│ AC-2 ⏳       │   └──────┘      └──────┘   └────────┘  └────────┘            │  task, inbox…  │
│ AC-3 ❌ 0.20  │                                                              │ hidden: —      │
│               │                                                              │ tool calls (7) │
│ OPEN ISSUES 2 │                                                              │ ▸ fs.edit …    │
├───────────────┴──────────────────────────────────────────────────────────────┴────────────────┤
│ ⏮ ◀ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━  seq 214 / 214  LIVE ▶ ⏭   🔍 filter │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Header
- Status pill + **state stepper** (the current state is highlighted; loops show as a back-arrow with a count badge, e.g. `TEST ↺3`).
- **Budget meters**: tokens, cost, fix cycles, wall clock. They turn amber at 75% and red at 90%. They are driven by `mission.budget`.
- Pause, abort, and a `⌘K` command palette.

### 4.2 Left rail
- **Plan board**: tasks with status glyphs, attempts count and assignee avatar. Clicking a task opens it in the Inspector. `↺` opens a **plan version diff** (v1 → v2, with `revised_because` and linked findings).
- **Acceptance criteria**: Given/When/Then shown on hover. Status chip plus a **confidence ring** (deterministic confidence). Clicking shows the checks (probe / property / differential / mutation) with evidence chips.
- **Open issues / prompts**: pending human prompts pinned at the top, with a pulse animation.

### 4.3 Center tabs

| Tab | What it shows | Key interactions |
|---|---|---|
| **Guild** | Live agent graph: nodes = agent instances (dynamic: `samurai#1..N`, candidates), positioned by guild. Edges = messages/findings/handoffs, animated when sent and labelled by type. Node ring = current mode, with a spinner while an LLM turn is running and token streaming shown in a tooltip. | Click a node → Inspector shows the agent's turns; click an edge → the message |
| **Timeline** | Virtualised event list grouped by mode invocation (collapsible). Icons per event type and colour per agent. Filters: agent, type, task, "decisions only", "loops only". | Click → Inspector; `Space` toggles live-follow |
| **Trace** | Waterfall of spans (mission → modes → LLM turns/tool calls), with parallel lanes for concurrent agents. Hover shows tokens, cost, latency and cache-hit %. | Zoom/pan; click span → Inspector |
| **Diff** | Monaco diff `baseline ↔ main` (or any checkpoint / candidate via a dropdown). **Gutter decorations** for review findings (amber), security findings (red), culprit hunks from ddmin (purple), and lines covered by acceptance tests (green dots). | Click a decoration → finding detail |
| **Tests** | **Test matrix heatmap**: rows = tests (acceptance tests marked ★), columns = test runs over time, cells coloured by outcome, ⚡ for flaky, regression cells outlined. Summary sparkline of failing count. | Click a cell → evidence log (JUnit message, traceback) |
| **Tournament** | k candidate cards side-by-side: strategy hint, score radar (pass rate, mutation kill, convention similarity, diff size, lint), gate badges and the judge's rationale. The winner is crowned and the losers are greyed out. | Open any candidate's diff |
| **Memory** | Memories recalled this mission (and why), memories written (with evidence) | — |

### 4.4 Inspector (right, resizable)
Context-sensitive detail for the selected entity:
- **Agent turn / mode invocation:** mode id, purpose, tier → model, thinking budget, **context slices included and hidden** (information hiding made visible), the thinking summary (collapsed), each tool call (name, rationale, args, result, evidence chip), token usage, and the submitted output rendered as structured cards (not raw JSON; a raw toggle is available).
- **Decision:** trigger, dossier (legal actions with cost estimates), chosen action highlighted, justification, cited evidence chips, guard overrides shown as red banners.
- **Evidence:** kind, argv, exit code, workspace sha, duration, and the full log with ANSI colours (`ansi-to-html`).
- **Finding / message / dispute:** thread view.

### 4.5 Time-travel scrubber (bottom)
- A slider over `seq`. Dragging fetches `GET /missions/{id}?at_seq=` (debounced at 150ms) and `diff?at_seq=`, so the whole UI renders the past state. Tick marks show key events (decisions = diamonds, test runs = dots coloured by verdict, human gates = flags).
- A `LIVE` button returns to the live stream.

## 5. Human gates (global modal layer)

| Gate | UI |
|---|---|
| Clarification | Card with question, 2–4 option tiles (label + consequence), free-text, "use default" |
| Command approval | Shows argv and the reason the agent wants it; Allow once / Deny |
| Escalation | Summary of what was tried (attempts with hypotheses + fingerprints), Shogun's question, options: give guidance / accept partial / abort |
| Dispute | Two columns (author vs critic) with their evidence; rule for one side or add guidance |
| **Apply gate** | Full-screen sheet: outcome badge, AC table with confidence, test summary (regressions highlighted), review/security results, **unverified claims list**, embedded Monaco diff, buttons *Approve & Apply* (requires typing the mission short id when any AC is not VERIFIED) / *Request changes* (free text → Shogun) / *Reject* |

Gates also trigger a browser notification and a tab-title badge when the tab is hidden.

## 6. Launchpad
- Repo picker: fixture cards (from `/api/fixtures`, with scenario badges) + a custom path input with validation.
- Request textarea with example chips per fixture.
- Profile segmented control: **Fast** (no tournaments, no premortem, sonnet everywhere) · **Balanced** (default) · **Careful** (plan gate on, tournaments on medium risk, mutation testing on).
- Mode toggle: Multi-agent / Single-agent baseline. Optional "Replay cassette" select.
- Recent missions table (status, outcome, cost, duration).

## 7. Report page
Print-friendly rendering of the deterministic report: **Verified / Failed / Unverified / Model claims** sections, feedback-loop narrative (auto-generated from DECISION events), plan history, budget usage and an evidence appendix. Export buttons: Markdown, HTML, JSON.

## 8. Eval dashboard
- Grouped bars: hidden-test pass rate, multi vs single, per fixture.
- Scatter: cost vs quality per run.
- Table: false-success count (must be 0 for multi), security recall, fix cycles.
- Each data point links to its mission.

## 9. Design system — "Sumi & Vermilion"

| Token | Dark (default) | Light |
|---|---|---|
| `--bg` | `#0E0F12` (sumi ink) | `#F7F5F0` (washi) |
| `--panel` | `#16181D` | `#FFFFFF` |
| `--border` | `#262A33` | `#E4E0D6` |
| `--text` | `#E8E6E1` | `#1B1C1F` |
| `--muted` | `#8A8F98` | `#6B6F76` |
| `--accent` (vermilion) | `#E34234` | `#C8321F` |
| `--ok` | `#3FB27F` | `#2E8B57` |
| `--warn` | `#E0A526` | `#B7791F` |
| `--fail` | `#E5484D` | `#C53030` |

Agent colours (used consistently on nodes, timeline, avatars and trace lanes):
Shogun `#E34234` · Scout `#4FA3E0` · Samurai `#D4A84B` · Sentinel `#3FB27F` · Verifier `#A78BFA` · Reviewer `#F472B6` · Security `#94A3B8` · Human `#FFFFFF`/`#111`.

- Fonts: **Inter** (UI), **JetBrains Mono** (code/IDs), **Shippori Mincho** for the wordmark and section headings only.
- Motion: 150–250ms ease-out. Message edges animate a travelling dot. Respect `prefers-reduced-motion`.
- Density: compact (13px base in panels). All panels are resizable (`react-resizable-panels`) and the layout is persisted in localStorage.
- Accessibility: every status is conveyed by icon + text, not colour alone. Full keyboard navigation (`j/k` in the timeline, `g g` / `G` for scrubber start/end).
- Responsive: ≥1280 three panes. 768–1279: the Inspector becomes a drawer. <768: single column with tabs (read-only monitoring).

## 10. Frontend architecture

```
web/src/
├── app/                routes (react-router), providers (Query, theme, hotkeys)
├── api/                rest.ts (fetch wrappers), ws.ts (reconnecting socket, frame handling)
├── store/              missionStore.ts (Zustand: mission, events[], selection, scrubber, liveFollow)
├── types/generated.ts  ← generated, do not edit
├── features/
│   ├── launchpad/  header/  plan/  acceptance/  guild/  timeline/  trace/
│   ├── diff/  tests/  tournament/  memory/  inspector/  scrubber/  gates/  report/  eval/  modes/
├── components/ui/      shadcn components
└── lib/                format.ts (tokens, cost, durations), agentColors.ts, eventMeta.ts (icon/label per EventType)
```
Store rules:
- `mission` is replaced on `hello` and patched on `patch`. `events` are appended (ephemeral `AGENT_TEXT_DELTA` go to a separate `streams[agentId]` ring buffer of 4 KB).
- `selection: {kind, id}` drives the Inspector. Every clickable entity calls `select()`.
- When the scrubber is not live, WS frames are buffered and applied when returning to live.

## 11. Demo mode
`/m/:id?demo=1` hides the budget's dollar values, enlarges fonts by 10% and auto-follows the active agent. The Guild Graph zooms to the active edge. Useful for projecting.
