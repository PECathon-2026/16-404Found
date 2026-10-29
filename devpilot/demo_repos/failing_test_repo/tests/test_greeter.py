"""Tests for greeter module - will fail due to wrong function name."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# This import fails because greeter.py has 'greet' not 'say_hello'
from greeter import say_hello


def test_say_hello():
    """say_hello('World') returns 'Hello, World!'"""
    assert say_hello("World") == "Hello, World!"


def test_say_hello_empty():
    """say_hello with empty string still works."""
    assert say_hello("") == "Hello, !"
