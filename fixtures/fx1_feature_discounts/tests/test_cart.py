"""Unit tests for the shopcart package."""

import pytest
from shopcart.cart import Cart, Item
from shopcart.pricing import round_money


def test_empty_cart_total() -> None:
    cart = Cart()
    assert cart.total() == 0.0
    assert cart.item_count == 0


def test_add_single_item() -> None:
    cart = Cart()
    cart.add("Widget", 12.50)
    assert cart.total() == 12.50
    assert cart.item_count == 1


def test_add_multiple_items() -> None:
    cart = Cart()
    cart.add("Widget", 10.00)
    cart.add("Gadget", 15.00)
    assert cart.total() == 25.00
    assert cart.item_count == 2


def test_add_item_with_quantity() -> None:
    cart = Cart()
    cart.add("Book", 8.25, quantity=3)
    assert cart.total() == 24.75
    assert cart.item_count == 3


def test_items_list_immutability() -> None:
    cart = Cart()
    cart.add("Pen", 1.50)
    items = cart.items
    items.append(Item("Paper", 5.00))
    assert cart.item_count == 1


def test_negative_price_raises_error() -> None:
    cart = Cart()
    with pytest.raises(ValueError):
        cart.add("Invalid", -5.00)


def test_invalid_quantity_raises_error() -> None:
    cart = Cart()
    with pytest.raises(ValueError):
        cart.add("Item", 10.00, quantity=0)


def test_round_money_precision() -> None:
    assert round_money(10.125) == 10.13
    assert round_money(10.124) == 10.12
    assert round_money(0.0) == 0.0


def test_round_money_negative_raises_error() -> None:
    with pytest.raises(ValueError):
        round_money(-1.0)


def test_subtotal_calculation() -> None:
    cart = Cart()
    cart.add("Item A", 2.50, quantity=2)
    cart.add("Item B", 1.25, quantity=4)
    assert cart.subtotal() == 10.00
    assert cart.total() == 10.00
