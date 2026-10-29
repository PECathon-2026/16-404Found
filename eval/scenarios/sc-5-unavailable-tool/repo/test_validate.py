import unittest

from validate import validate_name


class ValidateName(unittest.TestCase):
    def test_strips(self):
        self.assertEqual(validate_name("  Ana "), "Ana")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            validate_name("  ")
