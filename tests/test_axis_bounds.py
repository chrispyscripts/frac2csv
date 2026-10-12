"""Value axes fitted from OCR'd tick labels: two ways a good ladder read wrong.

00248 (Carmine, #823, #826, #827):
  - the offset chart stacks four colours' labels at every gridline, so each
    colour's labels sit up to 30 px off their lines and the fit is shifted
    whole; snap_axis then snapped red's 0..80 to 75..-5;
  - the rate ladder 16.00 / 12.00 / 8.000 / 4.000 / 0.0 read with dropped
    decimals, and RANSAC found a line rising DOWN the page: 4311 m3/min.

  python3 -m unittest tests.test_axis_bounds
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_raster as ar                                 # noqa: E402

Y0, Y1 = 400, 1051                                       # 00248 p24's frame


class PrintedBounds(unittest.TestCase):
    def test_a_stack_shifted_ladder_is_put_on_the_frame(self):
        # red 80/60/40/20/0, each label 25 px above its gridline
        grid = [Y0 + k * (Y1 - Y0) / 4.0 for k in range(5)]
        pts = [(80 - 20 * k, grid[k] - 25, True) for k in range(5)]
        a, b, _n = ar.fit_ticks_guarded(pts)
        self.assertGreater(abs((a + b * Y0) - 80), 2.5)    # the shift
        self.assertEqual(ar.printed_bounds(pts, a, b, Y0, Y1), (80.0, 0.0))

    def test_a_ladder_that_stops_a_tick_short_is_left_alone(self):
        # 0..60 printed, the frame reaching on to 80
        grid = [Y0 + k * (Y1 - Y0) / 4.0 for k in range(5)]
        pts = [(80 - 20 * k, grid[k], True) for k in range(1, 5)]
        a, b, _n = ar.fit_ticks_guarded(pts)
        self.assertIsNone(ar.printed_bounds(pts, a, b, Y0, Y1))

    def test_snap_alone_gets_the_shifted_ladder_wrong(self):
        # the failure printed_bounds exists for
        top, bot, snapped = ar.snap_axis(76.9, -3.4)
        self.assertTrue(snapped)
        self.assertEqual((top, bot), (75.0, -5.0))


class UprightFit(unittest.TestCase):
    def test_a_ladder_read_with_dropped_decimals_fits_upright(self):
        # 00248 p91's cyan rate ladder as the OCR returned it
        pts = [(16.0, 351, True), (1200.0, 500, True), (1200.0, 518, True),
               (8.0, 684, True), (4000.0, 849, True), (0.0, 1016, True)]
        a, b, _n = ar.fit_ticks_guarded(pts)
        self.assertLess(b, 0)
        self.assertAlmostEqual(a + b * 351, 16.0, delta=0.5)
        self.assertAlmostEqual(a + b * 1016, 0.0, delta=0.5)

    def test_one_wild_label_does_not_drag_the_fit(self):
        # 00095 p119's clean-rate ladder, with "1678" and stray title digits
        pts = [(20.0, 9, True), (16.0, 156, True), (12.0, 303, True), (2.0, 319, True),
               (3.0, 330, True), (2.0, 371, True), (1678.0, 449, True), (8.0, 449, True),
               (4.0, 596, True), (0.0, 743, True)]
        a, b, _n = ar.fit_ticks_guarded(pts)
        self.assertAlmostEqual(a + b * 9, 20.0, delta=0.3)
        self.assertAlmostEqual(a + b * 743, 0.0, delta=0.3)

    def test_no_fit_runs_downward(self):
        pts = [(0.0, 100, True), (10.0, 200, True), (20.0, 300, True),
               (30.0, 400, True)]
        self.assertIsNone(ar.fit_ticks_guarded(pts))


class CoilNames(unittest.TestCase):
    def test_the_coil_rate_is_named(self):
        self.assertEqual(ar.match_legend_name(ar._legend_name("COIL #1 FLUID RATE (m3/min)")),
                         "Coil Fluid Rate")
        self.assertEqual(ar._VOCAB_UNIT["Coil Fluid Rate"], "m3/min")


if __name__ == "__main__":
    unittest.main()
