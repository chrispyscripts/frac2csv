"""STEP 1: the end of a chart is the curve finishing, not a logo.

auto_raster.drop_glyph_islands clears FracPro's logo, which prints inside
the plot in the series' own inks, by condemning small dense blobs that sit
clear of the trace. At shutdown the pressure falls near-vertically; that
fall is a one-pixel anti-aliased line the colour mask largely misses, and
what follows it — the hold, the drop, the pen resting at zero — arrives as
small dense pieces with nothing joining them to the trace. They were
condemned exactly like logo glyphs: on 00100 p197 the pressure ink runs to
column 831 and the trace stopped at 748, and the export lost the whole
shutdown (Carmine: "we lose a lot of data on the ends of the charts").

  python3 -m unittest tests.test_glyph_chart_ends
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import numpy as np                                       # noqa: E402

import auto_raster as ar                                 # noqa: E402

H, W = 300, 600


def chart():
    m = np.zeros((H, W), bool)
    for c in range(5, 501):                       # the curve, row ~100
        r = 100 + int(3 * np.sin(c / 20.0))
        m[r:r + 2, c] = True
    for c0 in (200, 240, 280):                    # the logo: top band, dense
        m[6:24, c0:c0 + 22] = True
        m[10:20, c0 + 6:c0 + 16] = False
    m[160:299, 503:509] = True                    # the shutdown fall, to zero
    m[297:299, 560:591] = True                    # the pen resting at zero
    m[60:64, 540:544] = True                      # a stray fleck, clear of all
    return m


def gone(before, after, rows, cols):
    r0, r1 = rows
    c0, c1 = cols
    return before[r0:r1, c0:c1].any() and not after[r0:r1, c0:c1].any()


class ChartEnds(unittest.TestCase):

    def setUp(self):
        self.m = chart()
        self.out = ar.drop_glyph_islands(self.m)

    def test_the_logo_still_goes(self):
        for c0 in (200, 240, 280):
            self.assertTrue(gone(self.m, self.out, (6, 24), (c0, c0 + 22)), c0)

    def test_the_shutdown_and_the_zero_line_stay(self):
        self.assertTrue(self.out[160:299, 503:509].any())
        self.assertTrue((self.out[160:299, 503:509] == self.m[160:299, 503:509]).all())
        self.assertTrue(self.out[297:299, 560:591].all())

    def test_a_fleck_standing_off_past_the_end_still_goes(self):
        self.assertTrue(gone(self.m, self.out, (60, 64), (540, 544)))

    def test_the_curve_is_untouched(self):
        self.assertTrue((self.out[90:110, 5:501] == self.m[90:110, 5:501]).all())

    def test_a_shutdown_only_goes_down(self):
        # 00163 p195: the curve is on the floor; past its end another pen's
        # anti-aliased fall, in this curve's colour, stands well above it
        m = np.zeros((H, W), bool)
        for c in range(5, 501):
            m[290:292, c] = True                       # the curve, on the floor
        for c0 in (200, 240):
            m[6:24, c0:c0 + 22] = True                 # a logo, so there is
            m[10:20, c0 + 6:c0 + 16] = False           # something to judge
        m[150:190, 506:512] = True                     # 40 rows, 100 above it
        out = ar.drop_glyph_islands(m)
        self.assertTrue(gone(m, out, (150, 190), (506, 512)))
        self.assertTrue(out[290:292, 5:501].all())

    def test_the_trace_keeps_every_reading_it_had(self):
        # the end pieces add readings where there were none; where the old
        # trace read the curve, the new one reads it the same
        old = ar.curve_positions(ar.drop_glyph_islands(self.m, ends=False), glyphs=False)
        new = ar.curve_positions(self.m, glyphs=True)
        had = np.isfinite(old)
        self.assertTrue(np.array_equal(old[had], new[had]))
        self.assertGreater(int(np.isfinite(new[501:]).sum()), int(had[501:].sum()))

    def test_the_bug_this_answers(self):
        tree = os.environ.get("F2C_OLD_TREE", "")
        old = os.path.join(tree, "auto_raster.py")
        if not tree or not os.path.exists(old):
            self.skipTest("set F2C_OLD_TREE to a v1.11.35 tree to compare")
        spec = importlib.util.spec_from_file_location("ar_old", old)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(gone(self.m, mod.drop_glyph_islands(self.m), (160, 299), (503, 509)))


if __name__ == "__main__":
    unittest.main()
