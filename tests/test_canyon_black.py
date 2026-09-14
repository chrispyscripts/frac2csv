"""Canyon: black is the curve AND the axis, and the tick marks are the axis.

  python3 -m unittest tests.test_canyon_black
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canyon                                             # noqa: E402


class P:
    def __init__(self, x, y):
        self.x, self.y = x, y


class BlackSegments(unittest.TestCase):

    def test_a_tick_mark_is_not_the_curve(self):
        # 00229 p37: (116.5, 326.6) -> (116.5, 324.2), the time axis's tick
        self.assertFalse(canyon._black_is_curve(P(116.5, 326.6), P(116.5, 324.2)))

    def test_a_long_frame_line_is_not_the_curve(self):
        self.assertFalse(canyon._black_is_curve(P(77.6, 171.3), P(77.6, 324.2)))     # frame
        self.assertFalse(canyon._black_is_curve(P(77.6, 324.2), P(546.8, 324.2)))    # baseline

    def test_the_curve_is_the_curve(self):
        self.assertTrue(canyon._black_is_curve(P(115.1, 186.7), P(115.4, 187.9)))
        self.assertTrue(canyon._black_is_curve(P(467.6, 197.5), P(467.7, 206.7)))   # steep, not vertical

    def test_a_short_hold_at_one_value_is_kept(self):
        self.assertTrue(canyon._black_is_curve(P(200.0, 190.0), P(203.0, 190.0)))


if __name__ == "__main__":
    unittest.main()
