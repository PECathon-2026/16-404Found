import pytest

from cart import price_of, total


def test_total():
    assert total(["apple", "fig"]) == 4.5


def test_unknown_item():
    with pytest.raises(KeyError):
        price_of("kiwi")
