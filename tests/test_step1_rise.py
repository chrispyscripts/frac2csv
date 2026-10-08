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

    def test_the_upright_trailing_edge_is_not_a_dip(self):
        # 00051 p159: up to ~26, two columns still reading the bottom of the
        # thick upright (~12), then ~22-27 again: the page draws no dip
        m = np.zeros((H, W), bool)
        m[286:290, 0:10] = True
        for c in range(10, 13):
            m[150:290, c] = True                 # the upright
        for c in (13, 14):
            m[150:240, c] = True                 # its trailing edge, top to ~mid
        m[160:166, 15:40] = True                 # carrying on at ~the top
        py = np.full(W, np.nan)
        py[0:10] = 287.5
        py[10:13] = [150.0, 289.0, 150.0]
        py[13:15] = 239.0
        py[15:] = 162.5
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(out[13:15] < 170), out[10:16])

    def test_a_real_dip_after_the_peak_is_kept(self):
        # 00051 p156: up to 30, a drawn dip to 23 held for columns, then on
        m = np.zeros((H, W), bool)
        m[286:290, 0:10] = True
        for c in range(10, 13):
            m[150:290, c] = True
        for c in range(13, 20):
            m[150:200, c] = True                 # the dip, a band 150-200
        m[150:156, 20:40] = True
        py = np.full(W, np.nan)
        py[0:10] = 287.5
        py[10:13] = [150.0, 289.0, 150.0]
        py[13:20] = 199.0                        # held at the dip
        py[20:] = 152.5
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(out[13:20] == 199.0), out[10:21])

    def test_a_repair_never_reads_past_the_curve_nearby(self):
        # 00006 p144: the riser's ink runs on above where the curve goes; its
        # edge read 691 against a step to ~470
        m = np.zeros((H, W), bool)
        m[286:290, 0:10] = True
        for c in range(10, 14):
            m[20:290, c] = True                  # ink far above the step
        m[160:166, 14:40] = True                 # the step's level
        py = np.full(W, np.nan)
        py[0:10] = 287.5
        py[10:14] = [160.0, 289.0, 289.0, 289.0]
        py[14:] = 162.5
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(out[11:14] >= 159.9), out[10:15])   # not up at row 20

    def test_a_real_spike_on_a_fall_is_kept(self):
        # 00048 p139: a needle up during a fall is the page's, and stays
        m = np.zeros((H, W), bool)
        m[150:156, 0:10] = True
        for c in range(10, 14):
            m[150:290, c] = True                 # the fall
        m[40:200, 14] = True                     # a needle up off it
        m[284:290, 15:40] = True
        py = np.full(W, np.nan)
        py[0:10] = 152.5
        py[10:14] = [289.0, 289.0, 289.0, 289.0]
        py[14] = 40.0
        py[15:] = 287.0
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertEqual(out[14], 40.0)

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
