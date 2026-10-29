from pricing import discount


def test_discount_rules():
    # Two stakeholders wrote contradictory requirements into one test.
    assert discount(100) == 90
    assert discount(100) == 80
