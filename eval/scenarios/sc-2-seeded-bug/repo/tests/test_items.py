from items import ITEMS, page, total_pages


def test_first_page_has_ten_items():
    assert page(ITEMS, 1, 10)[0] == "item-1" and len(page(ITEMS, 1, 10)) == 10


def test_total_pages():
    assert total_pages(ITEMS, 10) == 3
