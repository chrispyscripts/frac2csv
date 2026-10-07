"""STEP 1: how far the page keeps a curve's end height inked (_held_ends).

A curve that goes blank in mid-air is either still there under another pen,
which keeps its row inked, or gone down to the floor, which leaves its row
blank. And only a curve that was settled at that height is held: an end that
is one short piece may be another pen misread, and holding it along that pen
spreads the misreading (00108 p291).

  python3 -m unittest tests.test_step1_held_ends
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import step1                                             # noqa: E402

H, W = 200, 400
# value = a + b * absolute row, frame top at y0 = 0: row 0 is 1.0, row 200 is 0
A, B, Y0, TB = 1.0, -0.005, 0, 1.0                       # 1 s per column
NAN = float("nan")


def held(ink, v):
    return step1._held_ends(ink, np.asarray(v, float), A, B, Y0, TB, 1.0)


class HeldEnds(unittest.TestCase):

    def test_a_curve_under_another_pen_is_held_as_far_as_the_row_is_inked(self):
        ink = np.zeros((H, W), bool)
        ink[180, 200:350] = True                          # another pen at 0.1
        v = [0.1] * 200 + [NAN] * 200
        self.assertEqual(held(ink, v)["trail"], 349)

    def test_a_curve_gone_to_the_floor_is_not_held(self):
        ink = np.zeros((H, W), bool)
        v = [0.1] * 200 + [NAN] * 200
        self.assertIsNone(held(ink, v)["trail"])

    def test_a_short_piece_is_not_held_along_the_pen_it_may_belong_to(self):
        ink = np.zeros((H, W), bool)
        ink[168, 0:260] = True                            # a pen at 0.16 throughout
        v = [NAN] * 200 + [0.16] * 60 + [0.05] * 140      # a minute "at 0.16"
        self.assertIsNone(held(ink, v)["lead"])

    def test_settled_counts_readings_not_minutes(self):
        # 53560 p377: 0.091 for minutes, hidden for five, then a short piece
        ink = np.zeros((H, W), bool)
        ink[182, 260:330] = True
        v = [0.09] * 150 + [NAN] * 100 + [0.09] * 10 + [NAN] * 140
        self.assertEqual(held(ink, v)["trail"], 329)

    def test_a_settled_lead_is_held_back(self):
        ink = np.zeros((H, W), bool)
        ink[180, 50:200] = True
        v = [NAN] * 200 + [0.1] * 200
        self.assertEqual(held(ink, v)["lead"], 50)


if __name__ == "__main__":
    unittest.main()
