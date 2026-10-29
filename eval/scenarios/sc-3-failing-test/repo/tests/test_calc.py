from calc import add, total


def test_add():
    assert add(2, 3) == 5


def test_add_zero():
    assert add(0, 0) == 0


def test_total_rounds_to_two_decimals():
    assert total([0.11, 0.22, 0.333]) == 0.66
