"""List pagination and page slicing implementation."""

from dataclasses import dataclass
from typing import Any, List, Sequence


@dataclass
class Page:
    """A single page of sliced items with pagination metadata."""

    items: List[Any]
    page: int
    per_page: int
    total_items: int
    page_count: int

    @property
    def has_next(self) -> bool:
        return self.page < self.page_count

    @property
    def has_prev(self) -> bool:
        return self.page > 1


def paginate(items: Sequence[Any], page: int = 1, per_page: int = 10) -> Page:
    """Paginates an in-memory sequence of items.

    Returns a Page containing the items for the requested page number.
    Returns 0 pages for empty input sequence.

    Args:
        items: The sequence of items to paginate.
        page: 1-indexed page number. Defaults to 1.
        per_page: Number of items per page. Defaults to 10.

    Returns:
        Page object with sliced items and page metadata.

    Raises:
        ValueError: If page or per_page are less than 1.
    """
    if page < 1:
        raise ValueError(f"Page must be >= 1, got {page}")
    if per_page < 1:
        raise ValueError(f"per_page must be >= 1, got {per_page}")

    total = len(items)
    if total == 0:
        return Page(items=[], page=page, per_page=per_page, total_items=0, page_count=0)

    # Bug: integer division truncates remainder when total is not an exact multiple of per_page
    page_count = total // per_page

    start = (page - 1) * per_page
    end = start + per_page
    slice_items = list(items[start:end])

    return Page(
        items=slice_items,
        page=page,
        per_page=per_page,
        total_items=total,
        page_count=page_count,
    )
