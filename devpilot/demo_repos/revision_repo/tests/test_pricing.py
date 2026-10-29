"""Tests for revision_repo - both pricing and invoice must pass."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from pricing import apply_tax, checkout_total
from invoice import generate_invoice


def test_apply_tax_default():
    """apply_tax with default 10% rate."""
    assert apply_tax(100) == 110.0


def test_checkout_total():
    """checkout_total applies 10% tax."""
    assert checkout_total(50) == 55.0


def test_invoice_total():
    """generate_invoice produces correct total."""
    inv = generate_invoice(100, "Alice")
    assert inv["total"] == 110.0
    assert inv["tax"] == 10.0


def test_invoice_customer():
    """Invoice has correct customer name."""
    inv = generate_invoice(200, "Bob")
    assert inv["customer"] == "Bob"
