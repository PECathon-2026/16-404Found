"""Shopping cart pricing."""

PRICES = [("apple", 1.0), ("pear", 2.0), ("fig", 3.5)]


def price_of(name):
    for n, p in PRICES:
        if n == name:
            return p
    raise KeyError(name)


def total(names):
    return sum(price_of(n) for n in names)
