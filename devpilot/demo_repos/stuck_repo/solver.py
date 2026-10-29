"""Stuck repo - a problem that cannot be solved within the retry limit."""


def compute_answer() -> int:
    """Return the answer. This function has a dependency on an external service that always fails."""
    # BUG: this function calls an external service that always returns wrong results
    # The 'fix' is not possible without network access or the external service
    import random
    # Simulate an unreliable external dependency
    value = random.randint(1, 100)
    # The test expects exactly 42, but random always gives a different value
    return value
