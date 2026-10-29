# 12 — Mission Control: The War Room UI

The UI is a first-class product surface: it is how judges experience *transparency*, *coordination* and *human oversight*. It supersedes ADR-010 (CLI-first). The CLI remains for scripting and evaluation.

## 0. Product direction (decided)

| Decision | Choice |
|---|---|
| Platform | **Web app first** (React SPA served by the Python backend). **Desktop via Tauri 2** with the Python engine bundled alongside is a stretch goal (WP-G17), using the same code. No native or Electron app. |
| Concept | **A war room, not an IDE.** The user is a commander watching a campaign unfold: agents as living entities in a spatial scene, findings as light travelling between them. Code is one zoom level deep, never the home screen. |
| Aesthetic | **"Sumi & Vermilion"**: ink-wash (sumi-e) darkness, film grain, frosted glass HUD panels, vermilion accents, soft bloom. References: Linear / Vercel / Raycast / Arc polish with a Japanese campaign theme. |
| Two presentation modes | **Cinematic** (default for demo: stage + HUD) and **Focus** (calm, flat, dense three-pane layout for deep inspection). The toggle is `F`. Both are driven by the same store. |

### Design laws
1. **Motion = meaning.** Every animation is triggered by a real `Event` and encodes information (who, what kind, outcome). No idle decoration except the ambient layer, which itself encodes mission health.
2. **Every glyph is inspectable.** Anything that moves can be clicked → Inspector shows the underlying event and evidence.
3. **Never block reading.** Animations never delay data. State updates instantly and the animation plays *over* the already-correct state, so a frame drop never lies.
4. **Graceful degradation.** WebGL fails → 2D canvas; `prefers-reduced-motion` → fades only; low GPU → quality tier `low`. The demo must survive a weak projector laptop.
5. **Calm by default, loud on consequence.** Most motion is ≤ 250 ms and subtle. Big set-pieces are reserved for test failures, verification seals, tournaments and the apply decree.

---

## 1. Stack

| Concern | Choice |
|---|---|
| App | **Vite + React 18 + TypeScript (strict)** in `web/` |
| Styling | **Tailwind CSS v3 + shadcn/ui** (Radix), `lucide-react` |
| UI motion | **`motion`** (Framer Motion) springs, layout animations, `AnimatePresence`; **View Transitions API** for route changes |
| Choreography | **GSAP 3** timelines for set-pieces (hanko stamp, decree scroll, tournament split) |
| 3D / shaders | **three + @react-three/fiber + @react-three/drei + @react-three/postprocessing** (bloom, vignette, noise) |
| 2D graph | **@xyflow/react** + `elkjs` (Focus mode graphs, plan DAG, 2D constellation fallback) |
| Code | **@monaco-editor/react** diff editor with decorations |
| Data | **Zustand** (live store) + **TanStack Query** (REST) |
| Lists | **react-virtuoso** |
| Charts | **Recharts** + custom SVG (trace waterfall, heatmap) |
| Palette | **cmdk** |
| GPU tiering | **detect-gpu** → quality tier `high | medium | low` |
| Sound (optional, muted by default) | **howler** |
| Markdown | `react-markdown` + `remark-gfm` + `rehype-highlight` |
| Types | Generated from pydantic: `scripts/gen_types.py` → `web/src/types/generated.ts`. **Never hand-write API types.** |
| Tests | Vitest + Testing Library; Playwright e2e against the fake mission server; Playwright screenshot tests for key states |
| Desktop (stretch) | **Tauri 2** with the PyInstaller-built `devpilot serve` binary bundled alongside |

> **Agent emblems are code-drawn** (SVG + `motion`), not Rive/Lottie files. AI coding agents cannot author binary animation assets reliably. If a human designer joins, Rive can replace them behind the same `<AgentEmblem state>` interface.

---

## 2. Backend API (FastAPI, `devpilot/api/`)

### REST
| Method | Path | Body / Query | Returns |
|---|---|---|---|
| POST | `/api/missions` | `{repo_path, request, mode: "multi"\|"single", profile: "fast"\|"balanced"\|"careful", replay_cassette?, chaos?}` | `{id}` (mission starts asynchronously) |
| GET | `/api/missions` | | `MissionSummary[]` |
| GET | `/api/missions/{id}` | `?at_seq=` (time travel) | `Mission` |
| GET | `/api/missions/{id}/events` | `?from_seq=&to_seq=&types=` | `Event[]` |
| GET | `/api/missions/{id}/keyframes` | | `Keyframe[]` (see §6.9) |
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
```ts
type Frame =
  | { kind: "hello"; mission_id: string; last_seq: number; snapshot: Mission }
  | { kind: "event"; event: Event }                       // every event incl. ephemeral AGENT_TEXT_DELTA
  | { kind: "patch"; seq: number; ops: JsonPatchOp[] }   // RFC 6902 patch of Mission after event seq
  | { kind: "heartbeat"; ts: string };
```
- The server sends **JSON Patch** diffs after each persisted event. The UI applies them with `fast-json-patch` and **never re-implements projection logic**.
- On reconnect the client sends `from_seq = lastSeenSeq + 1`. If the gap is larger than 500 events, the server sends a fresh `hello`.
- Client → server: `{kind:"answer", prompt_id, choice?, free_text?}`, `{kind:"ping"}`.

---

## 3. Information architecture

```
/                      Launchpad ("The Gate")
/m/:id                 War Room (Cinematic by default; F → Focus)
/m/:id/report          Mission Report ("The Chronicle"), print-friendly
/eval                  Evaluation dashboard ("The Proving Ground")
/modes                 Mode Registry explorer ("The Codex")
```

---

## 4. The War Room: Cinematic layout

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ⛩ DEVPILOT   "Users report the last page…"      ◉ EXECUTING  ↺2     ⏱ 03:12   ◔ tokens 31%  ⌘K │  ← Command Bar (glass)
├──────────────┬───────────────────────────────────────────────────────────────┬─────────────────┤
│ CAMPAIGN MAP │                                                               │  INSPECTOR      │
│  (glass)     │                 ✦ Shogun                                      │  (glass drawer, │
│  ┌──┐  ┌──┐  │          ✧ Scout          ✦ Verifier                          │   slides in on  │
│  │T1│━━│T2│  │                    ·  ·  ·  · ⟶ (finding particle)            │   selection)    │
│  └──┘  └──┘  │      ✦ Sentinel ━━━━━━━━━━━━━━━━━━━▶ ✦ Samurai#1 ⟳ (loop ring) │                 │
│     ┃        │                                         "thought stream" ▏    │                 │
│   ┌──┐       │      ✧ Reviewer        ✧ Security                            │                 │
│   │T3│       │                                                               │                 │
│   └──┘       │            THE STAGE: Guild Constellation (3D / 2D)           │                 │
│ ACCEPTANCE   │                                                               │                 │
│ ┌AC-1┐ 印    │                                                               │                 │
│ ┌AC-2┐ …     │                                                               │                 │
├──────────────┴───────────────────────────────────────────────────────────────┴─────────────────┤
│ ▣▣▣▣▣▣▣▣▣▣▣▣▣▣▣▣▣▣▣▣◆▣▣▣▣▣▣▣▣▣▣▣ ● LIVE       Film strip (keyframe thumbnails, scrubbable)       │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
          Ambient Mood layer (full-bleed shader behind everything)
```
- The **Stage** is full-bleed and fills the center. HUD panels are frosted glass (`backdrop-blur-xl`, 8% white fill, 1px inner border, grain overlay) floating over it.
- The left HUD (**Campaign Map + Acceptance seals**) collapses to an icon rail with `[`. The Inspector opens on selection and closes with `Esc`.
- The bottom **Film strip** is always visible. The Command Bar is at the top.
- **Focus mode (`F`)** morphs (shared-layout animation, 400 ms) into the classic three-pane layout: left Plan/ACs, center tabs (Timeline, Diff, Tests, Trace, Tournament, Memory), right Inspector, bottom scrubber. The Stage shrinks into a small "minimap" tile in the corner, still live.

---

## 5. Motion system

### 5.1 Tokens (`web/src/motion/tokens.ts`)
```ts
export const dur = { instant: 0.08, fast: 0.15, base: 0.25, slow: 0.45, epic: 1.2 } as const;      // seconds
export const ease = {
  out:   [0.16, 1, 0.3, 1],        // UI entrances
  inOut: [0.65, 0, 0.35, 1],       // camera, morphs
  ink:   [0.7, 0, 0.2, 1],         // brush wipes
} as const;
export const spring = {
  snappy: { type: "spring", stiffness: 520, damping: 38 },
  soft:   { type: "spring", stiffness: 220, damping: 26 },
  heavy:  { type: "spring", stiffness: 140, damping: 18, mass: 1.4 },   // seals, decree
} as const;
```

### 5.2 FX Bus: the single place that maps events to animations
```ts
// web/src/motion/fxBus.ts
type Fx =
  | { kind: "particle"; from: AgentId; to: AgentId | TaskKey; tone: Tone; label: string; eventSeq: number }
  | { kind: "pulse"; agent: AgentId; tone: Tone }
  | { kind: "emblemState"; agent: AgentId; state: EmblemState }
  | { kind: "seal"; acId: string; result: "verified" | "failed" }
  | { kind: "loopTick"; taskKey: string; attempt: number; hypothesis: string; strategyChanged: boolean }
  | { kind: "ripple"; origin: AgentId; tone: "fail" | "ok" }
  | { kind: "mood"; target: Mood }
  | { kind: "camera"; focus: AgentId | "overview" }
  | { kind: "tournament"; phase: "split" | "score" | "crown"; taskKey: string; candidates: string[]; winner?: string }
  | { kind: "mapInk"; taskKey: string; status: TaskStatus }
  | { kind: "sound"; cue: SoundCue };

export function eventToFx(e: Event, m: Mission): Fx[];   // pure, unit-tested
```
- `eventToFx` is **pure and exhaustively tested** (one test per `EventType`).
- An `FxQueue` rate-limits effects: at most 6 concurrent particles; bursts of the same kind within 300 ms coalesce into one with a ×N badge. During scrubbing and replay at >2× speed, only `mapInk`, `seal` and `mood` play.
- Reduced motion: `particle`, `ripple` and `camera` become no-ops; `seal` and `mapInk` become 150 ms fades.

### 5.3 Choreography table (event → effect)

| Event | Effect(s) | Timing |
|---|---|---|
| `MODE_STARTED` | `emblemState(agent, thinking)` + `camera(agent)` if the stage is in auto-follow + node orb brightens | emblem 250 ms; camera 900 ms `inOut` |
| `AGENT_TEXT_DELTA` | Thought Stream appends tokens (blur-in per word) | 120 ms per word, batched per frame |
| `TOOL_CALL` | `emblemState(agent, tool)`; tool chip slides out of the orb into the stream | 200 ms `snappy` |
| `POLICY_DENIED` | Chip shatters into 6 shards + red outline flash on the orb; `sound(deny)` | 350 ms |
| `TOOL_UNAVAILABLE` / `CIRCUIT_OPENED` | Chip greys and swaps to its fallback name with a flip | 300 ms |
| `MESSAGE_SENT` / `FINDING` | `particle(sender → recipient or task)` along a bezier arc; tone by type (finding = amber, verdict = violet, request = blue, dispute = magenta); the recipient pulses on arrival | 700–1100 ms by distance |
| `TEST_RUN` green | Sentinel lantern glows green, soft `ripple(ok)` | 600 ms |
| `TEST_RUN` red | Lantern flares red; `ripple(fail)` across the stage; `mood(strained)`; affected task tile shakes 2 px ×3 | 800 ms |
| `DECISION` | Diamond glyph drops from the Shogun orb onto the target task; label shows the action (`RETRY`, `INVESTIGATE`…) | 600 ms `heavy` |
| `GUARD_OVERRIDE` | Diamond is struck by a vermilion bar, label swaps to the forced action | 400 ms |
| `STRATEGY_CHANGED` | The task's loop ring **cracks and re-forms** in a new hue | 900 ms GSAP |
| `MODEL_ESCALATED` | Samurai orb grows a second halo (frontier tier) | 500 ms |
| `TOURNAMENT_STARTED` | `tournament(split)`: Samurai orb splits into k orbs that fan out | 1.2 s `epic` |
| `TOURNAMENT_SCORED` | Score bars rise beneath each candidate | 600 ms staggered 80 ms |
| `TOURNAMENT_DECIDED` | `tournament(crown)`: winner gets a vermilion crown glyph and drifts back to center; losers fade to 20% and drift away | 1.4 s |
| `PLAN_ADOPTED` (v2+) | Campaign Map redraws with a full **ink-brush wipe** (shader mask); changed regions glow | 1.0 s `ink` |
| `TASK_STATE_CHANGED` | `mapInk`: region fills with ink proportional to status (READY outline → IN_PROGRESS brush stroke → DONE solid ink); ESCALATED flickers | 500 ms |
| `AC_STATUS_CHANGED` → VERIFIED | **Hanko seal stamp** (§6.3) + `sound(seal)` | 650 ms |
| `AC_STATUS_CHANGED` → FAILED | Cracked seal | 500 ms |
| `HUMAN_PROMPT` | Stage dims to 40%; gate card rises; tab title badge; system notification if hidden | 450 ms |
| `HUMAN_DECISION` | Gate card folds away; the answer flies as a white particle to the Shogun | 600 ms |
| `CHECKPOINT` | New film-strip frame slides in from the right | 300 ms |
| `ROLLBACK` | Film strip rewinds visually to the checkpoint frame and the stage desaturates briefly | 800 ms |
| `BUDGET_WARNING` | Meter turns amber, `mood(pressured)` | 400 ms |
| `APPLIED` | Decree seal + gold mood + a slow confetti of ink particles (one-shot) | 2.0 s |
| `MISSION_FINISHED` | Camera pulls back to overview; final outcome banner brushes in | 1.5 s |

### 5.4 Sound (optional; muted by default; toggle in the Command Bar)
Cues: `tool` (soft wood tick), `deny` (dull clack), `fail` (low taiko hit), `ok` (bamboo chime), `seal` (stamp thud), `decree` (gong swell). Each is under 40 KB, CC0 licensed and listed in `web/public/sfx/LICENSES.md`. Max volume 0.35. At most one cue per 150 ms.

---

## 6. Signature components

### 6.1 Guild Constellation (`features/stage/`)
- **Model:** nodes = agent instances (static guild members + dynamic `samurai#N` / `cand-A..C`). Positions follow a **guild ring layout**: Council (Shogun, Scout) top, Forge (Samurai) right, Dojo (Sentinel, Verifier) bottom, Shadow (Reviewer, Security) left. Dynamic Samurai fan out around the Forge anchor.
- **3D version (`quality: high|medium`)**: R3F scene; each agent is an emissive sphere with a fresnel shader rim in the agent colour, plus an orbiting emblem sprite (rendered SVG → texture). Bloom (`luminanceThreshold 0.6`, intensity 0.9), vignette and a noise pass for grain. Particles are instanced meshes travelling along `CatmullRomCurve3` arcs with additive trails. The camera uses drei `CameraControls`: auto-follow the active agent (toggle `A`), free orbit on drag, double-click node → focus.
- **2D version (`quality: low` or WebGL unavailable)**: React Flow custom nodes (glowing CSS radial gradients + emblem) with an SVG path animation for particles. **Same `Fx` interface**, so it's swapped at the component boundary.
- Click orb → Inspector (agent turns). Click particle (pausable, `Space`) → Inspector (message/finding).
- Performance budget: 60 fps at 1080p on integrated GPUs for `medium`. DPR capped at 1.5. Rendering stops (`frameloop="demand"`) when the tab is hidden or nothing animates.

### 6.2 Agent Emblems (`features/emblems/`)
`<AgentEmblem role state size />`, code-drawn SVG with `motion` variants:

| Role | Emblem | `thinking` | `tool` | `success` | `error` |
|---|---|---|---|---|---|
| Shogun | Kabuto helmet crest | crest shimmer | — | crest glow | crest dims |
| Scout | Spyglass | lens sweep rotation | lens flash | — | lens fogs |
| Samurai | Katana | blade gleam travels | blade draws partially | sheathe click | blade chips |
| Sentinel | Paper lantern | flame flickers | flame brightens | green flame | red flare |
| Verifier | Balance scale | pans oscillate | one pan dips | pans level + glow | pans tilt hard |
| Reviewer | Brush & scroll | brush strokes | scroll unrolls | scroll seal | ink blot |
| Security | Shuriken | slow spin | fast spin | stops, glints | cracks |

States: `idle | thinking | tool | success | error | blocked`. Transitions are 200–300 ms springs, and idle has a 4 s subtle breathing scale (1 → 1.02).

### 6.3 Hanko Seals: Acceptance criteria (`features/acceptance/`)
- Each AC is a glass card (Given/When/Then, status, deterministic confidence ring, check chips: probe / property / differential / mutation).
- **VERIFIED stamp** (GSAP timeline, 650 ms): the seal (vermilion square with an SVG kanji 証 "proof" and the AC id) drops from scale 1.6 / opacity 0 / rotate −12° → scale 0.92 (impact at 220 ms, card shakes 1.5 px) → settles at 1.0, rotate −4°. An ink-bleed SVG turbulence filter expands 0 → 6 px then fades. 6 ink droplets spray.
- **FAILED**: a grey seal with a crack path drawn (`pathLength` 0 → 1), 500 ms.
- Hovering the seal → tooltip listing the evidence IDs. Click → Inspector.

### 6.4 Feedback Loop Ring (`features/loops/`)
- Attached to a task (on the map and on the Samurai orb). An SVG ring whose segments = attempts. Each segment is coloured by outcome and labelled on hover with **that attempt's hypothesis** and fingerprint.
- `loopTick`: a new segment sweeps in (500 ms) and the counter badge rolls (odometer) `↺1 → ↺2`.
- `strategyChanged`: the ring cracks (segments separate 6 px with rotation jitter) then re-forms in the next hue in the sequence (vermilion → indigo → gold), 900 ms.
- This is the visual proof of "new evidence changed what an agent does next". Clicking a segment opens a side-by-side **hypothesis diff** in the Inspector (attempt n vs n+1: hypothesis, evidence that triggered the change, diff delta).

### 6.5 Campaign Map: the plan (`features/campaign/`)
- Tasks are rendered as **territories**: Voronoi cells (d3-delaunay) seeded by the elk layout of the task DAG, drawn with a rough ink stroke (SVG `feTurbulence` + `feDisplacementMap`). Dependencies are dashed roads. An agent banner (small emblem flag) sits on the territory being worked on.
- Status fill: PENDING outline only · READY faint wash · IN_PROGRESS animated brush stroke filling 0→60% · REWORK hatched · DONE solid ink · ESCALATED vermilion flicker · CANCELLED fades with a strike.
- **Plan revision** (v2+): an ink-brush wipe transition (shader mask or SVG mask animation, 1.0 s) reveals the new map. Added territories glow and removed ones crumble. The `revised_because` banner shows linked findings.
- Header: `PLAN v2 ⟲` → popover with the version timeline.

### 6.6 Thought Stream (`features/stream/`)
- A narrow column anchored next to the active agent (Cinematic) or in the Inspector (Focus). Streams `AGENT_TEXT_DELTA` with per-word blur-in (`filter: blur(4px) → 0`, `opacity 0 → 1`, 120 ms).
- Tool calls interleave as **chips**: icon + tool name + rationale (1 line) + evidence ID badge. Click → evidence.
- The extended-thinking summary appears collapsed as "⋯ considered 3 approaches" and expands on click.
- Auto-scroll with "jump to live" when the user scrolls up.

### 6.7 Ambient Mood layer (`features/ambient/`)
- A full-screen fragment shader (R3F `<ScreenQuad>` or raw WebGL with a canvas fallback gradient) of slow domain-warped noise resembling ink diffusing in water.
- Moods → uniforms: `calm` (indigo/ink, speed 0.05), `working` (ink + faint vermilion veins, 0.08), `strained` (amber tint, 0.12, faint ripple rings), `failing` (red ripples spawned at the failing agent's screen position), `victorious` (gold veins, 0.04).
- Mood is a pure function of mission state: `mood = f(status, last test verdict, budget ratio, open escalations)`. Transitions lerp uniforms over 1.5 s.
- Maximum opacity is 35% under the HUD so text contrast stays ≥ 4.5:1 (checked in a screenshot test).

### 6.8 The Imperial Decree: Apply Gate (`features/gates/decree/`)
- A full-screen set-piece. The stage blurs and dims. A vertical **scroll unrolls** from the top (GSAP, 900 ms; paper texture via CSS gradients + grain), containing:
  - outcome banner, AC table with seals and confidence, test summary (regressions highlighted), review/security verdicts, the **unverified claims** list (amber), budget used, and an embedded Monaco diff (expandable).
- Actions:
  - **Approve & Apply**: **press-and-hold 1.5 s**. A circular progress ring fills; releasing early cancels. On completion a large vermilion seal stamps onto the scroll and `APPLIED` fires. If any AC is not VERIFIED, the user must also type the mission short id before the hold control activates.
  - **Request changes**: textarea → sent to the Shogun (the scroll rolls up and a white particle flies to the Shogun).
  - **Reject**: the scroll burns away from the edges (dissolve shader / CSS mask).
- Other gates (clarification, command approval, escalation, dispute) use a smaller **"Messenger card"** that rises from the bottom with option tiles (label + consequence). Disputes show author vs critic columns with their evidence.

### 6.9 Film Strip: time travel (`features/filmstrip/`)
- `GET /keyframes` returns `{seq, ts, kind, label, thumbnail_hint}` for key events (decisions, test runs, checkpoints, gates, plan versions, seals).
- The strip renders frames as small cards (icon + label + verdict colour). The playhead is draggable and `←/→` steps keyframes.
- Scrubbing: the store enters `history` mode → fetches `Mission?at_seq` (debounced 120 ms, cached LRU 50). All components render the historical snapshot, and the FX bus plays **reverse-safe** effects only (`mapInk`, `seal` un-stamp as a fade, `mood`).
- **Replay**: a ▶ button replays from the playhead at 1×/2×/4× by re-feeding stored events through `eventToFx`, so a finished mission can be "re-watched" during the demo.
- `LIVE ●` returns to the live stream (buffered frames are applied instantly).

### 6.10 Inspection surfaces (Focus tabs and Inspector)

| Surface | Spec |
|---|---|
| **Inspector** | Context-sensitive panel. For a mode invocation: mode, purpose, tier → model, thinking budget, **context slices included vs hidden** (hidden slices shown as locked chips with the tooltip "information hiding"), tool calls, usage, and the submitted output rendered as structured cards with a raw JSON toggle. For a decision: dossier, legal actions with cost estimates, chosen action, guard override banner, cited evidence. For evidence: argv, exit code, workspace sha, ANSI log. For a finding, message or dispute: thread. |
| **Timeline** | Virtualised, grouped by mode invocation, filters (agent, type, task, decisions only, loops only), live-follow. Rows animate in with `layout` springs. |
| **Diff** | Monaco diff `baseline ↔ main` or any checkpoint/candidate. Gutter decorations: review (amber), security (red), ddmin culprit hunks (violet), acceptance-covered lines (green dots). |
| **Tests** | Heatmap: rows = tests (★ acceptance), columns = runs. Cells animate in column by column. Flaky ⚡, regression outline, sparkline of failing count. |
| **Trace** | SVG waterfall with lanes per concurrent agent, zoom/pan, hover tokens/cost/latency/cache-hit %. |
| **Tournament** | Arena view: k candidate cards with strategy hint, radar chart, gates and judge rationale. Winner crowned. Open any candidate diff. |
| **Memory** | Recalled memories (with match reason) and written memories (with evidence). |

### 6.11 Premium details (all surfaces)
- **Spotlight cursor**: a radial highlight follows the pointer on glass cards (CSS variables updated via `pointermove`, throttled with rAF).
- **Grain**: a fixed SVG noise overlay at 4% opacity (`mix-blend-mode: overlay`).
- **Odometer numbers** for tokens, cost, test counts and attempt counters (`motion` per-digit roll).
- **Magnetic buttons** on primary actions (±4 px pull).
- **View Transitions** between routes: shared-element morph of the mission title from Launchpad to War Room.
- **Command palette (⌘K)**: jump to agent/task/AC/evidence/event, toggle Focus/Cinematic, toggle sound, change quality, start replay.
- **Keyboard**: `F` focus mode, `A` auto-follow, `Space` pause particles, `[`/`]` toggle HUD panels, `←/→` keyframes, `Esc` close, `?` cheat sheet.

---

## 7. Launchpad ("The Gate")
- Hero: the DEVPILOT wordmark (Shippori Mincho) brush-revealed on load (stroke-dashoffset, 1.2 s), with the ambient shader in `calm`.
- **Fixture cards** (from `/api/fixtures`) in a bento grid with scenario badges, hover tilt (3°) + spotlight. Custom repo path input with live validation.
- Request composer: large textarea with example chips, a profile segmented control (**Fast / Balanced / Careful**), a multi/single toggle and an optional replay cassette.
- **"Begin Campaign"** button → View Transition into the War Room, with the stage assembling: agents fly in from the edges to their ring positions (staggered 60 ms).
- Recent missions table with outcome seals.

## 8. Report ("The Chronicle"), Eval ("The Proving Ground"), Codex
- **Chronicle**: print-friendly. Sections Verified / Failed / Unverified / Model claims, a loop narrative generated from DECISION events (each loop drawn as a mini ring), plan history, budget and evidence appendix. Export to MD/HTML/JSON. Light "washi" theme for printing.
- **Proving Ground**: grouped bars (hidden-test pass rate, multi vs single), a cost-vs-quality scatter, a false-success counter (should be 0 for multi), security recall and fix cycles. Each point links to its mission.
- **Codex**: Mode Registry explorer (cards per mode: agent emblem, tier, thinking budget, tools, visible/hidden slices, output schema viewer).

---

## 9. Design tokens

| Token | Dark (default) | Light (Chronicle/print) |
|---|---|---|
| `--bg` | `#0B0C0F` (sumi ink) | `#F7F5F0` (washi) |
| `--glass` | `rgba(255,255,255,0.06)` | `rgba(255,255,255,0.7)` |
| `--glass-border` | `rgba(255,255,255,0.10)` | `rgba(27,28,31,0.08)` |
| `--panel` | `#14161B` | `#FFFFFF` |
| `--text` | `#ECE9E2` | `#1B1C1F` |
| `--muted` | `#8A8F98` | `#6B6F76` |
| `--accent` (vermilion) | `#E34234` | `#C8321F` |
| `--gold` | `#D4A84B` | `#A9822D` |
| `--ok` | `#3FB27F` | `#2E8B57` |
| `--warn` | `#E0A526` | `#B7791F` |
| `--fail` | `#E5484D` | `#C53030` |
| `--glow-sm` / `--glow-lg` | `0 0 12px` / `0 0 40px` of the accent at 35% | none |

Agent colours: Shogun `#E34234` · Scout `#4FA3E0` · Samurai `#D4A84B` · Sentinel `#3FB27F` · Verifier `#A78BFA` · Reviewer `#F472B6` · Security `#94A3B8` · Human `#FFFFFF`.
Message tones: finding `#E0A526` · verdict `#A78BFA` · request/response `#4FA3E0` · dispute `#F472B6` · escalation `#E34234` · human `#FFFFFF`.

Fonts: **Inter** (UI), **JetBrains Mono** (code, IDs, numbers), **Shippori Mincho** (wordmark, section titles, seal labels only). Base size 14 px (Cinematic), 13 px (Focus).

Accessibility: every status has icon + text, contrast ≥ 4.5:1 over the ambient layer, full keyboard navigation, `prefers-reduced-motion` honoured globally, and the sound is off by default.

---

## 10. Frontend architecture

```
web/src/
├── app/                 routes, providers (Query, theme, hotkeys, quality tier), view transitions
├── api/                 rest.ts, ws.ts (reconnecting, from_seq)
├── store/               missionStore.ts (mission, events, streams, selection, history/live, presentation mode)
├── motion/              tokens.ts, fxBus.ts (eventToFx), FxQueue.ts, quality.ts (detect-gpu), sound.ts, mood.ts
├── types/generated.ts   ← generated
├── features/
│   ├── stage/           Constellation3D.tsx, Constellation2D.tsx, Particles, CameraRig, layout.ts
│   ├── emblems/         AgentEmblem.tsx + one file per role
│   ├── campaign/        CampaignMap.tsx (voronoi territories, ink filters, banners)
│   ├── acceptance/      ACCard.tsx, HankoSeal.tsx, ConfidenceRing.tsx
│   ├── loops/           LoopRing.tsx, HypothesisDiff.tsx
│   ├── stream/          ThoughtStream.tsx, ToolChip.tsx
│   ├── ambient/         AmbientShader.tsx, fallback.css
│   ├── gates/           Decree.tsx, HoldToConfirm.tsx, MessengerCard.tsx, DisputeCard.tsx
│   ├── filmstrip/       FilmStrip.tsx, replay.ts
│   ├── hud/             CommandBar.tsx, StateStepper.tsx, BudgetMeters.tsx, Odometer.tsx
│   ├── inspector/  timeline/  diff/  tests/  trace/  tournament/  memory/
│   ├── launchpad/  report/  eval/  codex/
├── components/ui/       shadcn + Glass.tsx, Spotlight.tsx, Grain.tsx, MagneticButton.tsx
└── lib/                 format.ts, agentColors.ts, eventMeta.ts
```

Store rules:
- `mission` is replaced on `hello` and patched on `patch`. `events` are appended. `AGENT_TEXT_DELTA` goes to `streams[agentId]` (ring buffer, 4 KB).
- `selection: {kind, id}` drives the Inspector. Every clickable entity calls `select()`.
- `presentation: "cinematic" | "focus"` and `quality: "high" | "medium" | "low"` are persisted in localStorage.
- `timeMode: "live" | "history" | "replay"`. Outside `live`, incoming frames are buffered.
- Animations subscribe to the **FX bus**, never to raw events. This keeps choreography testable and in one place.

Performance rules: lazy-load the R3F stage, Monaco and Recharts (route/feature code-splitting); the initial JS bundle is under 350 KB gzip. Pause rendering when the tab is hidden. Memoise selectors. No layout thrash (animate `transform`/`opacity` only outside of WebGL).

---

## 11. Demo mode
`/m/:id?demo=1` turns on Cinematic mode, auto-follow camera, sound on (low), 110% font scale, hidden dollar values and a slightly slower camera. Pressing `R` on a finished mission starts **Replay at 2×** from the first keyframe, so the full story can be re-watched on stage without re-running the agents.

## 12. Desktop packaging (stretch, WP-G17)
- `desktop/` Tauri 2 app wrapping `web/dist`. The Python backend is built with PyInstaller as `devpilot-server` and launched from Tauri on a random free port that the webview receives via an injected config.
- Native extras: system notifications for human gates, a tray icon showing mission status, and a native folder picker for the repo path. The window uses `titleBarStyle: Overlay` (macOS) / custom title bar (Windows) with the Command Bar acting as the drag region.
- Builds: `.dmg` (macOS arm64/x64), `.msi` (Windows). Unsigned is acceptable for the hackathon (documented).
