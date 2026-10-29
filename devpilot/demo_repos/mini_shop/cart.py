"""Cart module for mini_shop demo repo."""

from decimal import Decimal, ROUND_HALF_UP
from pricing import calculate_total, apply_coupon
from config import PAYMENT_API_KEY  # noqa: F401 - imported for payment integration


class Cart:
    """Shopping cart that holds items and computes totals."""

    def __init__(self):
        """Initialize an empty cart."""
        self.items = []

    def add_item(self, name: str, price: float, quantity: int = 1):
        """Add an item to the cart."""
        self.items.append({"name": name, "price": price, "quantity": quantity})

    def total(self) -> float:
        """Return the cart total as a float rounded to 2 decimal places."""
        raw = calculate_total(self.items)
        return float(Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def total_with_coupon(self, coupon_code: str) -> float:
        """Return total after applying a coupon code."""
        raw_total = calculate_total(self.items)
        discounted = apply_coupon(raw_total, coupon_code)
        return float(Decimal(str(discounted)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
