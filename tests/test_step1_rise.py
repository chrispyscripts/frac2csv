"""STEP 1: a steep rise drawn across several columns is one move, not a spike.

The 2026 STEP books (#799): the pressure goes straight from ~1 to ~30 MPa
across four pixel columns, each inked from the baseline up, and the export
read 0 -> 18 -> 0.7 -> 30 -> 0.8 — a false spike before every rise. A needle
(out and back) still keeps both ends; that is what _keep_excursions is for.

  python3 -m unittest tests.test_step1_rise
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import step1                                             # noqa: E402

H, W = 300, 40


def _sub_rise():
    m = np.zeros((H, W), bool)
    m[286:290, 0:10] = True                  # the baseline, ~1
    for c, top in zip(range(10, 14), (220, 200, 160, 160)):
        m[top:290, c] = True                 # the thick stroke, baseline up
    m[160:166, 14:40] = True                 # the hold at ~30
    return m


class Rise(unittest.TestCase):

    def test_a_multi_column_rise_never_falls_back(self):
        m = _sub_rise()
        py = np.full(W, np.nan)
        py[0:10] = 287.5                           # run middles, as traced
        py[10:14] = [220.0, 289.0, 289.0, 160.0]   # the envelope's flip-flop
        py[14:] = 162.5
        xs, rows = step1._keep_excursions(m, py)
        seg = rows[(xs >= 9) & (xs <= 15)]
        # rows grow downward: a rise is rows never increasing once it starts
        start = int(np.argmax(seg < 280))
        # never back down by more than a pen's width (the top of the stroke
        # sits a few rows above the hold's middle)
        self.assertTrue(np.all(np.diff(seg[start:]) <= 6.0), seg)
        self.assertLess(seg[start:].max(), 270, seg)            # no return to ~1

    def test_a_needle_keeps_its_depth(self):
        m = np.zeros((H, W), bool)
        m[160:166, :] = True                 # a level line
        m[160:290, 20] = True                # one column down to the floor and back
        py = np.full(W, 162.5)
        py[20] = 224.5                       # the run's middle, as traced
        xs, rows = step1._keep_excursions(m, py)
        self.assertGreaterEqual(rows.max(), 285)    # the needle's tip survives


if __name__ == "__main__":
    unittest.main()
