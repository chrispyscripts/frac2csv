"""A label OCR read twice, whole and as a fragment, is not a lost decimal point.

00007 p136 (2026 STEP) prints its pressure ladder 100, 75, 50, 25, 0. OCR read
the "50" twice, whole and as a "5" 14 px under it, plus a "7" from the axis
title. The fragment lands on the 0..100 line at ten times its value, so the
lost-point repair (built for 00208 p22's 10.0 / 7500 / 5000 / 2500 / 0) took the
axis to 0..10 and Surface Pressure went out ten times low on 7 charts.

Run: python3 -m unittest tests.test_ladder_fragment
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import auto_raster as ar  # noqa: E402

P136 = [(100.0, 9), (75.0, 201), (50.0, 391), (5.0, 405), (7.0, 430), (25.0, 586),
        (0.0, 779), (100.0, 9), (18.0, 201), (50.0, 394), (25.0, 586)]
P136_FIT = (101.11296343407061, -0.12991665227497962, 8)


class LadderFragment(unittest.TestCase):
    def test_fragment_of_a_whole_label_is_not_a_lost_point(self):
        out = ar._repaired_ladder(P136, P136_FIT)
        fit = out or P136_FIT
        top = fit[0] + fit[1] * 9
        self.assertAlmostEqual(top, 100.0, delta=3.0)

    def test_a_real_lost_point_is_still_repaired(self):
        # 00208 p22: 10.000, 7.500, 5.000, 2.500, 0.0 read 10.0, 7500, 5000, 2500, 0
        strict = [(10.0, 10), (7500.0, 110), (5000.0, 210), (2500.0, 310), (0.0, 410)]
        fit = ar.fit_ticks(strict, min_inliers=3)
        out = ar._repaired_ladder(strict, fit)
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out[0] + out[1] * 10, 10.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
