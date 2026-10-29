"""Financial calculation and rounding utilities."""

from decimal import Decimal, ROUND_HALF_UP


def round_money(amount: float) -> float:
    """Rounds a monetary value to two decimal places.

    Args:
        amount: The raw monetary amount to round.

    Returns:
        The amount rounded to 2 decimal places using standard half-up rounding.

    Raises:
        ValueError: If amount is negative or invalid.
    """
    if amount < 0:
        raise ValueError("Monetary amount cannot be negative")
    dec = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(dec)
