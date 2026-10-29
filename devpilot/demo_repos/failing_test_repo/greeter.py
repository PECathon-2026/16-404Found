"""Failing import test repo - wrong import causes test failure."""

# Note: this module has a wrong function name that the test imports
def greet(name: str) -> str:
    """Return a greeting string."""
    return f"Hello, {name}!"


# BUG: function should be named 'say_hello' but tests import 'say_hello' which doesn't exist
# The test imports say_hello but only greet is defined.
