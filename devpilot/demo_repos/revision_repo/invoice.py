"""Invoice module - uses apply_tax from pricing (the Planner's first plan will miss this)."""

from pricing import apply_tax


def generate_invoice(subtotal: float, customer: str) -> dict:
    """Generate invoice dict with subtotal, tax, and total."""
    total = apply_tax(subtotal)
    tax = total - subtotal
    return {
        "customer": customer,
        "subtotal": subtotal,
        "tax": round(tax, 2),
        "total": round(total, 2),
    }
