"""Shopping cart management and total cost calculations."""

from dataclasses import dataclass
from typing import List

from shopcart.pricing import round_money


@dataclass
class Item:
    """Represents a product item in a shopping cart.

    Attributes:
        name: Product name or SKU.
        price: Unit price in dollars.
        quantity: Number of units purchased.
    """

    name: str
    price: float
    quantity: int = 1


class Cart:
    """Shopping cart that aggregates items and calculates totals."""

    def __init__(self) -> None:
        """Initializes an empty shopping cart."""
        self._items: List[Item] = []

    def add(self, name: str, price: float, quantity: int = 1) -> None:
        """Adds an item to the shopping cart.

        Args:
            name: The product name or title.
            price: Unit price in dollars. Must be non-negative.
            quantity: Quantity to add. Defaults to 1. Must be positive.

        Raises:
            ValueError: If price is negative or quantity is less than 1.
        """
        if price < 0:
            raise ValueError(f"Price cannot be negative: {price}")
        if quantity < 1:
            raise ValueError(f"Quantity must be at least 1: {quantity}")

        self._items.append(Item(name=name, price=round_money(price), quantity=quantity))

    @property
    def items(self) -> List[Item]:
        """Returns a copy of the items currently in the cart."""
        return list(self._items)

    @property
    def item_count(self) -> int:
        """Returns the total number of physical units in the cart."""
        return sum(item.quantity for item in self._items)

    def subtotal(self) -> float:
        """Calculates the unrounded subtotal of all items.

        Returns:
            The raw sum of item price multiplied by quantity.
        """
        return sum(item.price * item.quantity for item in self._items)

    def total(self) -> float:
        """Calculates the final cart total.

        Returns:
            The rounded final total in dollars.
        """
        if not self._items:
            return 0.0
        raw = self.subtotal()
        return round_money(raw)
