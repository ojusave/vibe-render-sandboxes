"""Visible acceptance checks for the small sandbox coding exercise."""

# Python's built-in test library avoids downloading packages inside the deny-all sandbox.
import unittest

from stats import median


class MedianTests(unittest.TestCase):
    """Check the behavior a user expects from a median calculation."""

    def test_odd(self):
        # Sorting a three-item input should identify its middle value.
        self.assertEqual(median([9, 1, 5]), 5)

    def test_even(self):
        # An even-sized input uses the average of its two middle values.
        self.assertEqual(median([4, 1, 3, 2]), 2.5)

    def test_empty(self):
        # Empty input has no median, so callers need a clear error.
        with self.assertRaises(ValueError):
            median([])

    def test_original_unchanged(self):
        # Asking for a statistic must not rearrange the caller's list.
        original = [3, 1, 2]
        median(original)
        self.assertEqual(original, [3, 1, 2])


if __name__ == "__main__":
    # Running this file directly reports which expectations passed.
    unittest.main()
