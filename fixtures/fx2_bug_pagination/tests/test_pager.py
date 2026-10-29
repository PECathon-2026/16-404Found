"""Visible tests for the pager module covering standard usage and exact multiples."""

import pytest
from pager.paginate import paginate


def test_empty_list_returns_zero_pages() -> None:
    p = paginate([], page=1, per_page=10)
    assert p.items == []
    assert p.total_items == 0
    assert p.page_count == 0
    assert p.has_next is False
    assert p.has_prev is False


def test_exact_multiple_first_page() -> None:
    data = list(range(20))
    p = paginate(data, page=1, per_page=10)
    assert len(p.items) == 10
    assert p.items == list(range(10))
    assert p.page_count == 2
    assert p.has_next is True
    assert p.has_prev is False


def test_exact_multiple_second_page() -> None:
    data = list(range(20))
    p = paginate(data, page=2, per_page=10)
    assert len(p.items) == 10
    assert p.items == list(range(10, 20))
    assert p.page_count == 2
    assert p.has_next is False
    assert p.has_prev is True


def test_exact_multiple_five_per_page() -> None:
    data = list(range(15))
    p = paginate(data, page=3, per_page=5)
    assert len(p.items) == 5
    assert p.items == [10, 11, 12, 13, 14]
    assert p.page_count == 3


def test_invalid_page_number_raises_error() -> None:
    with pytest.raises(ValueError):
        paginate([1, 2, 3], page=0, per_page=10)


def test_invalid_per_page_raises_error() -> None:
    with pytest.raises(ValueError):
        paginate([1, 2, 3], page=1, per_page=0)
