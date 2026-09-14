"""Trican layout B colour masks: a stroke's fringe is its ink; the page is not.

  python3 -m unittest tests.test_trican_b_masks
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc                                # noqa: E402


def classify(rgb):
    img = np.array([[rgb]], dtype=int)
    m = tc.b_masks(img)
    hits = [k for k, v in m.items() if v[0, 0]]
    return hits[0] if hits else None


class Masks(unittest.TestCase):

    def test_the_pure_colours_are_themselves(self):
        for key, c, *_ in tc.B_SERIES:
            self.assertEqual(classify(c), key)

    def test_the_pink_fringe_of_a_steep_red_stroke_is_red(self):
        # 01433 p177, the #636 hole: (254,163,163) and (253,114,115) at 140+ from red
        for rgb in ((254, 163, 163), (253, 114, 115), (255, 104, 104), (248, 42, 44)):
            self.assertEqual(classify(rgb), "mainline", rgb)

    def test_monitor_pink_is_not_red_and_its_own_fringe_is_monitor(self):
        self.assertEqual(classify((189, 153, 153)), "monitor")
        self.assertEqual(classify((222, 204, 204)), "monitor")     # halfway to white

    def test_the_page_and_its_faintest_smudge_belong_to_nobody(self):
        self.assertIsNone(classify((255, 255, 255)))
        self.assertIsNone(classify((255, 236, 236)))               # 27 from the page: a smudge
        self.assertEqual(classify((255, 201, 201)), "mainline")    # 76 from the page, on red's line: fringe
        self.assertIsNone(classify((0, 0, 0)))

    def test_greys_are_no_nearer_than_before(self):
        # the axis-label grey is 67 from Monitor, outside the radius, and stays out
        self.assertIsNone(classify((122, 122, 122)))

    def test_olive_fringe_is_not_monitor(self):
        # (179,181,138): green ≥ red > blue — pale olive, 33 from Monitor's
        # pink and inside its old sphere. 237 such pixels on 01350 p187 had
        # been read as Monitor Pressure; they are WH Prop Conc's fringe.
        for rgb in ((179, 181, 138), (168, 171, 122), (184, 186, 146)):
            self.assertEqual(classify(rgb), "wh_conc", rgb)

    def test_the_two_olives_stay_apart(self):
        self.assertEqual(classify((92, 97, 5)), "wh_conc")
        self.assertEqual(classify((199, 204, 51)), "dh_conc")
        self.assertEqual(classify((150, 152, 90)), "wh_conc")      # olive's fringe, not DH


if __name__ == "__main__":
    unittest.main()
