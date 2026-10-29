# FX5b Notes (Hidden)

## Tool Outage Chaos Scenario
- Primary tools `search.rg` and `scan.bandit` are deliberately disabled.
- Agent must gracefully detect `TOOL_UNAVAILABLE` and fall back to pure-Python search and AST rule scanners.
