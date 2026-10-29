# AGENTS.md — Rules for AI coding agents (Gemini Antigravity, Claude, others)

You are working on **DevPilot**, a multi-agent AI engineering system built for a hackathon (PS-001). Quality bar: production-grade, fully typed, tested. The product is judged on **correctness, transparency, safety and UI polish**.

## Before you write code
1. Read `README.md`, then `docs/11-ADVANCED-ENGINE.md` (it supersedes older docs when they conflict), then the work packet you were given in `docs/13-BUILD-ORCHESTRATION.md`, then every doc that packet references.
2. Read the contracts: `devpilot/core/models.py`, `devpilot/core/events.py`, `devpilot/core/ports.py`, `devpilot/engine/modes.py`.

## Hard rules
- **Frozen contracts:** do NOT edit `devpilot/core/models.py`, `devpilot/core/events.py`, `devpilot/core/ports.py`, `devpilot/engine/modes.py`. Put needed changes under "Contract change requests" in your handoff note.
- **Implement against Protocols** in `ports.py`. Don't import concrete classes across subsystems; wire them in `devpilot/wiring.py`.
- **Safety:** never use `shell=True`, `os.system` or `eval`. All filesystem/process access from agent-facing code goes through the Tool Gateway. Never read or log `ANTHROPIC_API_KEY` or any secret.
- **Cross-platform:** use `pathlib` and `asyncio.create_subprocess_exec`. Code must pass on Windows and Linux. No bash-only scripts without a PowerShell twin.
- **No fake results:** never hard-code outputs, test results or eval numbers. Demo/fake data lives only in `devpilot/api/fake.py` and is labelled as fake in the UI.
- **Generated types:** never hand-edit `web/src/types/generated.ts`. Run `python scripts/gen_types.py`.
- **Scope:** do only your packet. Note other problems you find in the handoff note instead of fixing them.

## Python style
- Python 3.11, `from __future__ import annotations`, full type hints, `mypy --strict` clean for `devpilot/core`, `devpilot/engine`, `devpilot/tools`.
- pydantic v2 for data; `dataclass(slots=True)` for internal value objects.
- async-first: I/O functions are `async def`. Never block the event loop; use `asyncio.to_thread` for CPU or blocking libraries.
- Errors: raise specific exceptions; tools return `ToolResult(ok=False, error_code=...)` and never raise to the agent loop.
- Module docstring on every module; comments explain *why*, not what.
- Formatting/lint: `ruff check . && ruff format .` (line length 110).

## TypeScript / UI style
- `strict: true`, no `any` (use `unknown` + narrowing), function components and hooks, Zustand selectors to avoid re-renders.
- Tailwind + shadcn/ui only; use the design tokens in `docs/12` §9 via CSS variables, never raw hex in components.
- Every interactive element is keyboard accessible and has an aria-label. Status is never conveyed by colour alone.
- Each feature folder exports one top-level component; keep components under ~200 lines.

## Testing
- `python -m pytest -q` and `ruff check .` must pass before handoff. For web: `npm run typecheck && npm test`.
- Deterministic components (gateway, policy, workspaces, junit, fingerprint, repo intel, scanners, report engine) need thorough unit tests and **must not call an LLM**.
- Use `tmp_path` git repos for workspace tests. Never touch the real repo or `fixtures/` in place; copy first.

## Finishing a packet
Write `docs/handoffs/WP-XXX.md` (template in docs/13 §6) and tick nothing yourself in the tracker. The reviewer (Claude) ticks it after review.
