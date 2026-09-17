"""The envelope step must read a swept column at the ink's own ends.

A column's ink is split into runs, and a run taller than the pen is read at
whichever end lies further from the local trend — that is what traces a
transient instead of averaging it away. The ends used to be rebuilt from the
run's median and height as median ± height/2, which is the true extent only
when the run is filled evenly.

At a step down it is not. The ink is dense where the curve held and sparse
through the fall, so the median sits high in the run and the rebuilt end
lands outside the ink: 11.5 px past it on the run below. Outside the ink is a
row the pen never touched. Reported against Carmine's 00028 STEP charts as
"spikes ... far right of chart on the tr drop off ... should only be one line
not a second one spiking up" (#656, #658, #660) and, in the other direction
where the rebuilt end falls SHORT, as "not picking up the end of TR pressure"
(#655, #659) — one line, both complaints.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import auto_raster as ar                                 # noqa: E402


def step_down_mask(H=200, W=120, held=100, landed=160, at=60):
    """Flat, one column of fall, flat — the shape at a pressure drop off.

    The fall is drawn the way the mask actually catches a near-vertical
    stroke: solid where the pen held, then every other row on the way down.
    That matters. A CONTIGUOUS run's median is exactly its midpoint, so
    median ± height/2 and the run's own ends agree and the bug cannot show.
    The run here is one run — the holes are 1 row and `gap` tolerates 2 — but
    its median sits 10 px above its midpoint, and that is the asymmetry the
    rebuilt extents get wrong.
    """
    sub = np.zeros((H, W), bool)
    for cx in range(W):
        if cx < at:
            sub[held - 1:held + 2, cx] = True
        elif cx == at:
            sub[held:held + 21, cx] = True             # the pen holds
            sub[held + 22:landed + 1:2, cx] = True     # then falls, caught intermittently
        else:
            sub[landed - 1:landed + 2, cx] = True
    return sub


class SweptColumn(unittest.TestCase):
    def test_no_column_reports_outside_its_own_ink(self):
        # The invariant the rebuilt extents broke. Nothing else here matters
        # if this does not hold: a row with no ink is not a reading.
        sub = step_down_mask()
        py = ar.curve_positions(sub)
        for cx in range(sub.shape[1]):
            ys = np.flatnonzero(sub[:, cx])
            if not len(ys) or not np.isfinite(py[cx]):
                continue
            self.assertGreaterEqual(py[cx], ys[0] - 0.5, f"column {cx} above its ink")
            self.assertLessEqual(py[cx], ys[-1] + 0.5, f"column {cx} below its ink")

    def test_the_fall_is_read_to_the_bottom_not_short_of_it(self):
        # The truncation half: the curve is followed to where it lands.
        sub = step_down_mask()
        py = ar.curve_positions(sub)
        self.assertAlmostEqual(py[60], 160.0, delta=1.0)

    def test_the_held_level_either_side_is_untouched(self):
        sub = step_down_mask()
        py = ar.curve_positions(sub)
        self.assertAlmostEqual(py[59], 100.0, delta=1.0)
        self.assertAlmostEqual(py[61], 160.0, delta=1.0)

    def test_an_even_run_is_unchanged(self):
        # Where the ink IS even, median ± half and the real ends agree, so
        # this fix must be a no-op — most columns on every template.
        sub = np.zeros((80, 40), bool)
        sub[38:43, :] = True
        py = ar.curve_positions(sub)
        self.assertTrue(np.all(np.abs(py - 40.0) <= 1.0))


if __name__ == "__main__":
    unittest.main()
