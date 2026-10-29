"""Revision repo - function used in two places, plan only covers one initially."""


def apply_tax(amount: float, rate: float = 0.1) -> float:
    """Apply tax to an amount. Returns amount * (1 + rate)."""
    return amount * (1 + rate)


def checkout_total(cart_total: float) -> float:
    """Calculate checkout total including tax."""
    return apply_tax(cart_total)


# Note: apply_tax is ALSO used in the invoice module (which the Planner's first plan will miss)
