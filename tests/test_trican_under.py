"""Layout A: a curve hidden under a later-painted one (00026 p84, #646).

  python3 -m unittest tests.test_trican_under
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc                                 # noqa: E402

H, N, ROW = 40, 60, 20


def stroke(cols, row=ROW):
    """A 2 px pen along `row` in the given columns -> (mask, traced rows)."""
    sub = np.zeros((H, N), bool)
    py = np.full(N, np.nan)
    for c in cols:
        sub[row:row + 2, c] = True
        py[c] = row + 0.5
    return sub, py


class Under(unittest.TestCase):

    def test_surface_pressure_is_read_from_under_wh_rate(self):
        rate = stroke(range(N))
        surf = stroke(list(range(0, 20)) + list(range(40, N)))     # hidden 20..39
        notes = []
        got = tc._deduce_under({"surface": surf, "rate": rate}, notes)
        self.assertEqual(got, {"surface": 20})
        self.assertTrue(np.isfinite(surf[1]).all())
        self.assertTrue(np.allclose(surf[1][20:40], ROW + 0.5))
        self.assertEqual(notes, ["Surface Pressure: 20 columns read from under WH "
                                 "Rate where the page paints WH Rate over it and "
                                 "the two coincide — deduced, not traced"])

    def test_bh_pressure_walks_through_a_surface_that_was_itself_filled(self):
        # BH under Surface under Rate: BH is visible only at the ends, Surface
        # is hidden in the middle third — BH's whole run is reached because
        # Surface is filled first and its filled trace is the cover.
        rate = stroke(range(N))
        surf = stroke(list(range(0, 20)) + list(range(40, N)))
        bh = stroke(list(range(0, 10)) + list(range(50, N)))
        notes = []
        got = tc._deduce_under({"bh": bh, "surface": surf, "rate": rate}, notes)
        self.assertEqual(got, {"surface": 20, "bh": 40})
        self.assertTrue(np.isfinite(bh[1]).all())
        self.assertEqual([n.split(":")[0] for n in notes], ["Surface Pressure", "BH Pressure"])
        # the cover's MASK is empty where Surface was itself deduced, so BH
        # reaches those columns through WH Rate — one line names both
        self.assertIn("under Surface Pressure and WH Rate", notes[1])

    def test_a_curve_elsewhere_is_not_touched(self):
        # Surface runs ten rows above Rate: no column is under it, nothing fills
        rate = stroke(range(N), row=ROW + 10)
        surf = stroke(list(range(0, 20)) + list(range(40, N)))
        notes = []
        got = tc._deduce_under({"surface": surf, "rate": rate}, notes)
        self.assertEqual(got, {})
        self.assertEqual(np.isfinite(surf[1]).sum(), 40)
        self.assertEqual(notes, [])

    def test_a_missing_series_is_skipped(self):
        surf = stroke(range(0, 20))
        self.assertEqual(tc._deduce_under({"surface": surf}, []), {})

    def test_the_pairs_are_paint_order(self):
        # the cover of every pair is painted after its hidden curve
        order = [k for k, *_ in tc.SERIES]
        for hidden, cover in tc._UNDER_PAIRS:
            self.assertLess(order.index(hidden), order.index(cover), (hidden, cover))


if __name__ == "__main__":
    unittest.main()
