"""Tests for mini_shop cart and pricing."""

import sys
import os

# Allow running from both project root and demo_repos/mini_shop
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from cart import Cart


class TestCart:
    """Tests for the Cart class."""

    def test_add_single_item(self):
        """Cart correctly stores one item."""
        cart = Cart()
        cart.add_item("apple", 1.00)
        assert len(cart.items) == 1

    def test_total_single_item(self):
        """Total of a single item matches price."""
        cart = Cart()
        cart.add_item("apple", 2.50)
        assert cart.total() == 2.50

    def test_total_multiple_items(self):
        """Total sums all items correctly."""
        cart = Cart()
        cart.add_item("apple", 1.00, 3)
        cart.add_item("banana", 0.75, 2)
        # 3.00 + 1.50 = 4.50
        assert cart.total() == 4.50

    def test_rounding_three_items_at_9_99(self):
        """3 items at 9.99 with 10% coupon must total 29.97 (not 29.969...)."""
        cart = Cart()
        cart.add_item("widget", 9.99, 3)
        # Subtotal: 29.97
        # 10% of 29.97 = 2.997 -> rounds to 3.00
        # 29.97 - 3.00 = 26.97
        discounted = cart.total_with_coupon("SAVE10")
        assert discounted == 26.97, f"Expected 26.97, got {discounted}"

    def test_empty_cart_total(self):
        """Empty cart has zero total."""
        cart = Cart()
        assert cart.total() == 0.0


class TestPricing:
    """Tests for pricing module."""

    def test_invalid_coupon_raises(self):
        """Invalid coupon code raises ValueError."""
        from pricing import apply_coupon
        from decimal import Decimal

        with pytest.raises(ValueError):
            apply_coupon(Decimal("100"), "BADCODE")

    def test_large_coupon_no_negative(self):
        """A 50% coupon on a small amount does not go negative."""
        cart = Cart()
        cart.add_item("sticker", 0.10)
        result = cart.total_with_coupon("HALFOFF")
        assert result >= 0.0

    def test_quantity_math(self):
        """Quantity multiplied correctly."""
        cart = Cart()
        cart.add_item("pen", 1.50, 4)
        assert cart.total() == 6.00
