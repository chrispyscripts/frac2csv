"""STEP: Btm Prop Conc read from under Prop Conc where the two coincide.

  python3 -m unittest tests.test_step_under

00349 p138 lost 37.9% of Btm Prop Conc (#112) and 01316 stage 45 lost 80%
(#627): orange painted first, green over it, and where they coincide the
page shows green alone. The deduction: a curve with no ink inside its own
span is under another curve's stroke, and that stroke is where it is.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import step1                                              # noqa: E402

H, W = 300, 400


def stroke(mask, cols, rows, pen=3):
    for c, r in zip(cols, rows):
        mask[int(r) - pen // 2:int(r) + pen // 2 + 1, c] = True


class FillUnder(unittest.TestCase):

    def scene(self, green_rows_in_gap, riser=False):
        o = np.zeros((H, W), bool)
        g = np.zeros((H, W), bool)
        orange_row = np.full(W, 200.0)
        stroke(o, range(0, 150), orange_row[:150])            # orange visible …
        stroke(o, range(250, 400), orange_row[250:])          # … either side of the gap
        stroke(g, range(0, 400), np.full(W, 120.0))           # green somewhere else all along
        if green_rows_in_gap is not None:
            stroke(g, range(150, 250), green_rows_in_gap)     # green over the gap
        if riser:
            g[100:260, 180:184] = True                        # a tall green riser at col 180
        py_o = np.full(W, np.nan)
        py_o[:150] = 200.0
        py_o[250:] = 200.0
        # the cover's OWN trace: where curve_positions would put green — at
        # 120 everywhere, and over the gap wherever the gap stroke is
        py_g = np.full(W, 120.0)
        if green_rows_in_gap is not None:
            py_g[150:250] = np.asarray(green_rows_in_gap, float)
        return o, py_o, g, py_g

    def test_orange_under_green_is_deduced(self):
        o, py_o, g, py_g = self.scene(np.full(100, 201.0))   # green riding where orange is
        cols = step1._fill_under(o, py_o, g, py_g)
        self.assertEqual(cols, list(range(150, 250)))
        self.assertTrue(np.all(np.abs(py_o[150:250] - 201.0) < 1e-9))

    def test_green_elsewhere_does_not_fill(self):
        o, py_o, g, py_g = self.scene(None)                  # green stays at 120 in the gap
        cols = step1._fill_under(o, py_o, g, py_g)
        self.assertEqual(cols, [])
        self.assertTrue(np.all(np.isnan(py_o[150:250])))

    def test_a_drifting_cover_is_followed_but_a_jump_is_not(self):
        rows = 200.0 + np.linspace(0, 6, 100)                # green drifts 6 px across the gap
        o, py_o, g, py_g = self.scene(rows)
        self.assertEqual(len(step1._fill_under(o, py_o, g, py_g)), 100)
        rows = np.full(100, 230.0)                           # green 30 px away: not the same curve
        o, py_o, g, py_g = self.scene(rows)
        self.assertEqual(step1._fill_under(o, py_o, g, py_g), [])

    def test_a_riser_forces_nothing(self):
        o, py_o, g, py_g = self.scene(np.full(100, 201.0), riser=True)
        py_g[180:184] = 180.0                                # the tracer's median of the tall run
        cols = step1._fill_under(o, py_o, g, py_g)
        self.assertNotIn(180, cols)
        self.assertNotIn(183, cols)
        self.assertIn(150, cols)
        self.assertIn(249, cols)                             # reached from the right

    def test_outside_the_span_nothing_is_touched(self):
        o, py_o, g, py_g = self.scene(np.full(100, 201.0))
        py_o[300:] = np.nan                                  # orange ends at 300; green continues
        o[:, 300:] = False
        step1._fill_under(o, py_o, g, py_g)
        self.assertTrue(np.all(np.isnan(py_o[300:])))


class NotFromRawInk(unittest.TestCase):
    """00324: an orange glyph kept as a 654 'peak' must not chain along the
    green logo's ink. Only the cover's traced row counts."""

    def test_raw_green_ink_near_a_false_point_is_ignored(self):
        o = np.zeros((H, W), bool); g = np.zeros((H, W), bool)
        py_o = np.full(W, np.nan); py_o[:100] = 250.0; py_o[300:] = 250.0     # orange at the floor-ish
        py_o[100] = 40.0                                                       # a glyph kept as data
        stroke(o, range(0, 101), np.r_[np.full(100, 250.0), 40.0]); stroke(o, range(300, 400), np.full(100, 250.0))
        stroke(g, range(0, 400), np.full(W, 250.0))                            # green rides the floor too …
        g[35:45, 101:110] = True                                               # … and the logo's green sits near the glyph
        py_g = np.full(W, 250.0)                                               # the tracer puts green at the floor
        cols = step1._fill_under(o, py_o, g, py_g)
        self.assertTrue(all(abs(py_o[c] - 250.0) < 1e-9 for c in cols))       # nothing deduced near 40
        self.assertEqual(py_o[101], 250.0)          # reached from the right, at the floor — not from the glyph


class WhUnderDh(unittest.TestCase):
    """Trican layout B, 01350 p227: WH at the floor under DH's zero line."""

    def test_the_floor_is_deduced_from_the_cover_at_the_floor(self):
        import curve_trace as ct
        o = np.zeros((H, W), bool); d = np.zeros((H, W), bool)
        py_w = np.full(W, np.nan)
        stroke(o, range(0, 60), np.full(60, 120.0)); py_w[:60] = 120.0       # WH ramps down …
        stroke(o, range(60, 80), np.linspace(120, 297, 20)); py_w[60:80] = np.linspace(120, 297, 20)
        stroke(d, range(0, 400), np.full(W, 297.0))                           # DH on the floor all along
        py_d = np.full(W, 297.0)                                              # DH traced on the floor throughout
        cols = ct.fill_under(o, py_w, d, py_d)
        self.assertEqual(cols, [])                                            # nothing: WH's span ends at 80
        stroke(o, range(380, 400), np.full(20, 297.0)); py_w[380:] = 297.0    # … and comes back at the end
        cols = ct.fill_under(o, py_w, d, py_d)
        self.assertEqual(cols, list(range(80, 380)))
        self.assertTrue(np.all(py_w[80:380] == 297.0))


if __name__ == "__main__":
    unittest.main()
