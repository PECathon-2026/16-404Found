"""Hidden grading tests for FX1 discount code feature."""

import pytest
from shopcart.cart import Cart


def test_hidden_save10_discount() -> None:
    """SAVE10 provides 10% discount."""
    cart = Cart()
    cart.add("Item", 100.00)
    # Check if discount applied via apply_discount or total parameter
    if hasattr(cart, "apply_discount"):
        cart.apply_discount("SAVE10")
        assert cart.total() == 90.00
    else:
        assert cart.total(discount="SAVE10") == 90.00


def test_hidden_save10_rounding() -> None:
    """SAVE10 rounds discount properly using round_money."""
    cart = Cart()
    cart.add("Item", 19.99)
    # 10% of 19.99 = 1.999 -> discounted is 17.99
    if hasattr(cart, "apply_discount"):
        cart.apply_discount("SAVE10")
        assert cart.total() == 17.99
    else:
        assert cart.total(discount="SAVE10") == 17.99


def test_hidden_flat5_over_twenty() -> None:
    """FLAT5 applies $5 discount when order total exceeds $20."""
    cart = Cart()
    cart.add("Item A", 15.00)
    cart.add("Item B", 10.00)
    if hasattr(cart, "apply_discount"):
        cart.apply_discount("FLAT5")
        assert cart.total() == 20.00
    else:
        assert cart.total(discount="FLAT5") == 20.00


def test_hidden_flat5_not_applicable_under_twenty() -> None:
    """FLAT5 does not apply discount if order is <= $20."""
    cart = Cart()
    cart.add("Item", 18.00)
    if hasattr(cart, "apply_discount"):
        cart.apply_discount("FLAT5")
        assert cart.total() == 18.00
    else:
        assert cart.total(discount="FLAT5") == 18.00


def test_hidden_unknown_discount_code_raises_value_error() -> None:
    """Invalid discount code must raise ValueError following repo conventions."""
    cart = Cart()
    cart.add("Item", 50.00)
    with pytest.raises(ValueError):
        if hasattr(cart, "apply_discount"):
            cart.apply_discount("BOGUS_CODE")
            cart.total()
        else:
            cart.total(discount="BOGUS_CODE")


def test_hidden_discount_never_makes_total_negative() -> None:
    """Discount cannot reduce cart total below 0."""
    cart = Cart()
    cart.add("Small", 2.00)
    if hasattr(cart, "apply_discount"):
        try:
            cart.apply_discount("FLAT5")
        except ValueError:
            pass
        assert cart.total() >= 0.0
    else:
        assert cart.total(discount="FLAT5") >= 0.0


def test_hidden_empty_cart_discount() -> None:
    """Empty cart with discount remains 0.0."""
    cart = Cart()
    if hasattr(cart, "apply_discount"):
        cart.apply_discount("SAVE10")
        assert cart.total() == 0.0
    else:
        assert cart.total(discount="SAVE10") == 0.0


def test_hidden_existing_totals_unchanged_without_discount() -> None:
    """Cart without discount produces identical total."""
    cart = Cart()
    cart.add("Item", 35.50)
    assert cart.total() == 35.50
