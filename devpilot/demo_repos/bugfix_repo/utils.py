"""Off-by-one bug in list slicing - for bugfix_repo demo."""


def get_top_n(items: list, n: int) -> list:
    """Return the top n items from a list (highest values). Has a bug: returns n+1 items."""
    sorted_items = sorted(items, reverse=True)
    return sorted_items[:n + 1]  # BUG: should be [:n]


def sum_list(items: list) -> int:
    """Sum all items in a list."""
    total = 0
    for item in items:
        total += item
    return total
