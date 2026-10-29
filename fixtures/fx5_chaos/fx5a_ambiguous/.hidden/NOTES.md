# FX5a Notes (Hidden)

## Ambiguous Request Scenario
- Natural language request "Make the report faster" is inherently ambiguous.
- Shogun must trigger a CLARIFICATION gate offering choices:
  - Cache recent results
  - Optimize algorithm
  - Reduce calculation output
- Eval harness responds from `answers.json` selecting "cache results".
