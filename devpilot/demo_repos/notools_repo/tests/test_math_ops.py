"""Tests for notools_repo math_ops."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from math_ops import multiply, divide
import pytest


def test_multiply():
    """multiply(3, 4) == 12"""
    assert multiply(3, 4) == 12


def test_divide():
    """divide(10, 2) == 5.0"""
    assert divide(10, 2) == 5.0


def test_divide_by_zero():
    """divide by zero raises ZeroDivisionError."""
    with pytest.raises(ZeroDivisionError):
        divide(5, 0)
