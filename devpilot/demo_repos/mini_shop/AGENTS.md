"""Mini shop repo rules."""

# Repo Rules: mini_shop

- Use pytest for all tests. Run `pytest` from the repo root.
- Keep functions small and focused. One responsibility per function.
- **Never hardcode secrets.** Use environment variables or a secrets manager.
- Use `Decimal` for all money calculations. Never use plain `float` for prices.
- All public functions must have docstrings.
- Coupon codes are uppercase strings. Validate them before applying.
