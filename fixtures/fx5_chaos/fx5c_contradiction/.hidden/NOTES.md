# FX5c Notes (Hidden)

## Contradictory Test Chaos Scenario
- `test_contradictory_requirement_a` asserts `validate_token("admin_secret") is True`.
- `test_contradictory_requirement_b` asserts `validate_token("admin_secret") is False`.
- These assertions contradict each other on the exact same input.
- Samurai attempts will repeatedly fail with the same fingerprint.
- Guards trigger `STRATEGY_CHANGED`, escalating to `ASK_HUMAN`.
- Scripted eval provides `answers.json` ("accept partial"), terminating gracefully in `COMPLETED_PARTIAL` without infinite looping.
