# DevPilot: autonomous multi-agent engineering workspace

Turns a natural-language request into a tested, security-reviewed, **independently verified** change to an existing repository, then asks a human before anything is applied. Built for PECathon 2026 PS-001. Design docs: [`context/`](context/) (AGENTS, PLAN, ARCHITECTURE, UI-REGISTRY, PROGRESS-TRACKER).

## Run it
```sh
# backend (Python >= 3.11)
cd backend && python3 -m venv .venv && .venv/bin/pip install -e . pytest pytest-asyncio ruff asgi-lifespan
cp .env.example .env            # optional: add a model key (see below)
.venv/bin/python -m uvicorn app.main:app --port 8000

# frontend (Node >= 20), in another terminal
cd frontend && npm install && npm run build && npm run start -- -p 3000     # http://localhost:3000
```
**No API key?** Open *New mission → Demo scenario*. The model is scripted; tools, test runs, verifier, security scan, gate and approval are real.
**Live missions** need `ANTHROPIC_API_KEY`+`ANTHROPIC_MODEL` or `OPENAI_API_KEY`+`OPENAI_MODEL` (+`OPENAI_BASE_URL`; Gemini works via its OpenAI-compatible endpoint). No model id is hardcoded.

## Backend in Docker
```sh
docker build -t devpilot-backend ./backend
docker run -d --name devpilot -p 8000:8000 \
  -v devpilot-data:/data -v "$PWD/eval:/eval:ro" \
  --env-file backend/.env \          # optional: model keys, GITHUB_TOKEN (omit if no .env)
  devpilot-backend
# or: docker compose up -d --build
```
Data (DB, workspaces, reports) persists in the `devpilot-data` volume. Local-folder repositories must be mounted into the container to be importable (e.g. `-v "$HOME/projects:/projects"`, then import `/projects/my-app`); GitHub links work as-is. The sandbox inside the container is still the local jail, not a nested container.

## Work on a GitHub repository
*Repositories → paste `https://github.com/owner/repo`* (optional token for private repos). DevPilot clones into its own directory, works on an isolated copy, and on **approval** creates a new branch `devpilot/…` with one commit. **Pushing and opening a PR are opt-in checkboxes at approval time**, off by default; tokens are passed via env-config header, never stored or logged.

## How it works
Hub-and-spoke LangGraph: every worker returns to the **master**, which picks `PLAN / DELEGATE / EXECUTE / RETRY / REPLAN / VERIFY / ESCALATE / REQUEST_APPROVAL / COMPLETE / FAIL` from evidence. Agents: planner, developer (LLM tool loops), tester and security (deterministic, tool-driven), master (deterministic policy, optional LLM among legal actions), and a verifier that runs as a **separate OS process** (fresh clone of the base commit + patch only; imports no agent/DB code). Completion needs verifier PASS on every criterion, no open HIGH findings, green system-captured tests on the exact patch, and human approval bound to the patch hash.
Safety: path jail, command allowlist (no shell), existing tests protected + tamper detection, secret redaction, repeated-failure watchdog, budgets, escalation.

## Verify
`cd backend && .venv/bin/python -m pytest tests` (115 tests) · `cd frontend && npx tsc --noEmit && npx eslint . && npm run build`

## Known limitations (honest)
- **Sandbox is a local jail, not a container** (cwd/env/time/output limits + allowlist). A malicious repo's own test code can still read host files. Docker runner not implemented.
- Live Anthropic/OpenAI adapters are unit-tested for request/response mapping only; **never exercised against the real APIs** here (no keys).
- Only scenario SC-3 has a scripted fixture; SC-1/2/4/5/6/7 fixtures and the eval harness are not built (the underlying behaviours are covered by unit/integration tests).
- No Alembic, Postgres/Redis, crash-resume of in-flight missions, parallel developers, persistent memory, dependency audit, or cost estimation (reported as "no data"/unavailable, never faked).
- Python-first targets (pytest/unittest); `npm test` detected but needs installed deps.
