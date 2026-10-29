# DevPilot Project Rules

- Language: Python 3.11+. Tests: pytest.
- All results shown to judges must come from **real runs**. Never hand-write logs or test results.
- Every tool call goes through the safety layer. No exceptions.
- Agents work on a **temporary copy** of the target repo, never the original. Changes reach the original only after human approval.
- Keep files small and simple. Add a short docstring to every module.
- Every phase must have tests. Run `pytest` before saying a phase is done.
- Never commit API keys. Read them from `.env`.
- Do not add extra agents or features that are not in PLAN.md.
