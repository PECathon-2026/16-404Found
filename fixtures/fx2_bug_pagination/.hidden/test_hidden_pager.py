"""Hidden grading tests for FX2 pagination bug."""

from pager.paginate import paginate


def test_hidden_remainder_page_count() -> None:
    """10 items with 3 per page must yield 4 pages, not 3."""
    items = list(range(10))
    p = paginate(items, page=1, per_page=3)
    assert p.page_count == 4, f"Expected 4 pages for 10 items with 3 per page, got {p.page_count}"


def test_hidden_last_page_content_with_remainder() -> None:
    """The last page (page 4) of 10 items with 3 per page must contain the 1 remaining item."""
    items = list(range(10))
    p = paginate(items, page=4, per_page=3)
    assert p.items == [9], f"Expected last page to contain [9], got {p.items}"
    assert p.page_count == 4


def test_hidden_single_item_page_count() -> None:
    """1 item with per_page=10 must have page_count 1, not 0."""
    p = paginate(["only"], page=1, per_page=10)
    assert p.page_count == 1
    assert p.items == ["only"]


def test_hidden_odd_remainder_page_count() -> None:
    """7 items with 5 per page must yield 2 pages."""
    p = paginate(list(range(7)), page=2, per_page=5)
    assert p.page_count == 2
    assert p.items == [5, 6]


def test_hidden_empty_collection_page_count() -> None:
    """Empty list must return 0 pages per specification."""
    p = paginate([], page=1, per_page=5)
    assert p.page_count == 0
    assert p.items == []


def test_hidden_large_remainder() -> None:
    """101 items with 20 per page must yield 6 pages."""
    p = paginate(list(range(101)), page=6, per_page=20)
    assert p.page_count == 6
    assert p.items == [100]


def test_hidden_has_next_with_remainder() -> None:
    """has_next on page 3 of 4 must be True."""
    p = paginate(list(range(10)), page=3, per_page=3)
    assert p.has_next is True


def test_hidden_has_prev_on_last_remainder_page() -> None:
    """has_prev on page 4 of 4 must be True."""
    p = paginate(list(range(10)), page=4, per_page=3)
    assert p.has_prev is True
    assert p.has_next is False
