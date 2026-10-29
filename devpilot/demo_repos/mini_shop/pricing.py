"""Pricing module for mini_shop demo repo."""

from decimal import Decimal, ROUND_HALF_UP

# Coupon codes: code -> discount fraction
COUPONS = {
    "SAVE10": Decimal("0.10"),
    "SAVE20": Decimal("0.20"),
    "HALFOFF": Decimal("0.50"),
}


def calculate_total(items: list) -> Decimal:
    """Sum price * quantity for all items, using Decimal for precision."""
    total = Decimal("0")
    for item in items:
        price = Decimal(str(item["price"]))
        qty = Decimal(str(item["quantity"]))
        total += price * qty
    return total


def apply_coupon(total: Decimal, coupon_code: str) -> Decimal:
    """Apply a coupon discount. Returns discounted total (min 0)."""
    code = coupon_code.strip().upper()
    if code not in COUPONS:
        raise ValueError(f"Unknown coupon code: {coupon_code!r}")
    discount_fraction = COUPONS[code]
    discount_amount = (total * discount_fraction).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    discounted = total - discount_amount
    # Ensure total never goes negative
    return max(discounted, Decimal("0"))


def round_currency(value: Decimal) -> float:
    """Round a Decimal to 2 decimal places and return as float."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
