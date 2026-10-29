"""Tests for security_repo db module."""

import sys
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import safe_function


def test_safe_function():
    """safe_function works correctly."""
    assert safe_function(2, 3) == 5


def test_safe_function_negative():
    """safe_function handles negatives."""
    assert safe_function(-1, 1) == 0
