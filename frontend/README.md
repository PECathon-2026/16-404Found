# DevPilot · Mission control

A frontend for the DevPilot four-agent system. The Master coordinates an Architect (Planner), Engineer (Developer), Verifier, and Sentinel (Reviewer). Each has its own full-screen visual identity and evidence view.

## Run locally

Use Node.js 22.12+ (or a current LTS).

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Click **Play the journey**, then **Enter focus mode**. **Follow handoffs** switches screens as the active agent changes. The agent switcher lets you inspect each specialist independently. Escape returns to mission control; Cmd/Ctrl K opens a new mission.

```sh
npm test
npm run build
npm run test:e2e
```

Browser tests use installed Google Chrome on macOS when available. Else install Chromium with `npx playwright install chromium`, or set `CHROME_PATH` to an installed Chrome executable.

## Preview, recordings, and live evidence

- **Design preview** is a fictional coupon workflow. Its failure, retry, review finding, and approval screen illustrate interaction design. It never executes commands, changes repository files, exports run logs, or submits approval to a backend.
- **Recorded run** imports JSONL events from actual logs. Missing tests, criteria, or patch data remain absent. An imported recording cannot apply a change. Session history is in memory; previous live snapshots reopen as read-only recordings.
- **Live backend** connects through the settings button and polls a mission every 2.5 seconds. The updated backend is still needed. This frontend does not expose Python agents or API keys to the browser.

The current Python backend has not been modified by this frontend work. The live endpoints below are an integration contract, not a claim that they already exist in that backend.

## Backend contract

The API base defaults to `http://127.0.0.1:8000/api`. The backend must enable CORS for the frontend origin when using a different port. Authentication should be added to this adapter when the backend authentication model is known.

| Method | Path relative to API base | Request |
| --- | --- | --- |
| GET | `/missions/{id}` | Fetch current mission snapshot |
| POST | `/missions` | `{ "request": "…", "repository": "…" }` |
| POST | `/missions/{id}/approval` | `{ "decision": "approve" or "reject", "patch_hash": "…" }` |

Each successful response returns a complete `Mission` snapshot. Types live in [`src/lib/types.ts`](src/lib/types.ts); runtime validation and requests are in [`src/lib/transport.ts`](src/lib/transport.ts).

```ts
interface Mission {
  id: string
  request: string
  repository: string
  phase: 'planning' | 'building' | 'verifying' | 'reviewing'
    | 'awaiting_human' | 'done' | 'stopped' | 'escalated'
  activeAgent: 'master' | 'planner' | 'developer' | 'verifier' | 'reviewer'
  events: Array<{
    id: string; time: string; agent: Mission['activeAgent']
    type: string; summary: string; tool?: string; output?: string
  }>
  criteria: Array<{
    id: string; text: string; status: EvidenceStatus; evidence?: string
  }>
  changes: Array<{ path: string; before: string; after: string }>
  tests: Array<{ command: string; output: string; status: EvidenceStatus }>
  issues: Array<{
    id: string; text: string; file?: string
    severity: 'low' | 'medium' | 'high' | 'critical'
    status: 'open' | 'resolved'
  }>
  approvalEligible: boolean
  patchHash?: string
}
type EvidenceStatus = 'pending' | 'passed' | 'failed' | 'unavailable'
```

The client assigns `source: 'live'` after validating the response. It enables approval only with a live mission awaiting human review, a reviewable file change, a nonempty patch identity, backend eligibility, passing criteria with evidence, passing test records with output, and no open issues. The server must independently enforce the gate, bind verification and review to the exact patch, reject stale `patch_hash` values (for example with HTTP 409), and apply changes only after accepted approval. Client controls are presentation, not a security boundary.

JSONL imports support `time`, `agent`, `event_type`, `tool`, `input`, `output_summary`, and optional `output`. An unknown agent is displayed as Master. Summary text is not promoted into a fabricated test result. Imports are capped at 10 MB.

## Design and implementation

- React + TypeScript + Vite; Motion for screen transitions.
- Dark graphite, lime accents, editorial serif typography, and a live constellation map.
- Five procedural canvas identities: orbital network, blueprint lattice, code ribbon, scanning torus, and faceted shield.
- Activity, acceptance criteria, proposed changes, test output, and review findings remain inspectable.
- Responsive layouts from 320 px, keyboard focus containment and restoration, and reduced-motion support.
- Animation pauses when the document is hidden; device pixel ratio is capped at two.

Fonts load from Google Fonts with local fallbacks. An offline judging environment will use those fallbacks; self-host fonts before final submission if identical offline typography is required.

The frontend tests use isolated fixtures and are separate from DevPilot mission evidence. They must not be presented as successful AI-agent runs. No comparison scores or backend success rates are invented here.
