# CLAUDE.md — working on DevPilot

The shared agent rules are in `AGENTS.md` and apply here too. Claude owns the core packets (C01–C09) and reviews Gemini's packets (docs/13).

Read `README.md` and `docs/` before making changes. `docs/` is the source of truth for the design. If an implementation choice deviates from it, update the relevant doc in the same change.

- **Language:** Python 3.11+, asyncio, pydantic v2, typer, rich, the Anthropic SDK. No agent frameworks (see ADR-001).
- **Schemas:** all inter-agent contracts live in `devpilot/core/models.py`. Change them only with a team ping, because they are frozen interfaces.
- **Determinism boundary:** gateway, policy, guards, fingerprinting, the JUnit parser and the report engine must be pure code with unit tests that never call an LLM.
- **Never** let an LLM decide that an AC is VERIFIED. Only `report/engine.py` does that (docs/06 §6).
- **Safety:** every filesystem or process action goes through `tools/gateway.py`. Never use `shell=True`.
- **Paths:** use `pathlib` everywhere. The code must run on both Windows and Linux.
- **Tests:** `python -m pytest -q`. Lint: `ruff check .`
- **Results:** never hand-edit `eval/results.*`, and never present illustrative logs as real results.
