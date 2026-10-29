# FX1 Notes (Hidden)

## Planted Feature Requirements
- Support discount codes:
  - `SAVE10`: 10% discount on cart subtotal.
  - `FLAT5`: $5 discount on orders strictly over $20.00.
- Traps:
  - Must reuse `round_money` from `shopcart.pricing` to maintain consistency.
  - Total must never be negative.
  - Unknown discount codes must raise `ValueError`.
