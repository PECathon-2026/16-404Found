"""Pagination helpers."""

ITEMS = [f"item-{i}" for i in range(1, 26)]


def page(items, number, size):
    """Return page `number` (1-based) of `size` items."""
    start = max((number - 1) * size - 1, 0)
    return items[start:start + size]


def total_pages(items, size):
    return -(-len(items) // size)
