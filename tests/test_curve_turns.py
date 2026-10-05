"""envelope="turns": a swept column is read at its extreme only where the
curve turns.

The envelope step reads a run taller than the pen at whichever end lies
further from the local trend, which keeps a transient's height. On a steady
steep rise every column is such a run — the curve enters at one end and
leaves at the other — the trend lags it, and the chosen end flips from column
to column: Trican 1 (layout B) 47477 stage 43's pressure rise came out 0.6,
4.5, 10.2, 7.9, 3.0, 11.1, 21.3, 18.6 MPa where the chart draws a straight
climb. Carmine: "when the TR pressure goes up and down, the program is
hallucinating small spikes".

Run: python3 -m unittest tests.test_curve_turns
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import auto_raster as ar                                 # noqa: E402


def stroke(points, H=240, pen=2):
    """A polyline drawn into a mask the way a plotter's pen fills columns:
    every row the line passes through in a column is ink, plus the pen."""
    W = len(points) - 1
    sub = np.zeros((H, W), bool)
    for cx in range(W):
        a, b = points[cx], points[cx + 1]
        lo, hi = int(round(min(a, b))) - pen // 2, int(round(max(a, b))) + pen // 2
        sub[max(0, lo):min(H, hi + 1), cx] = True
    return sub


def rise_peak_fall(W=300):
    """Flat at row 200, a steep climb to a sharp peak at row 40, a steep fall
    back to row 120, flat — rows grow downward, so the climb runs 200 -> 40."""
    pts = []
    for x in range(W + 1):
        if x < 80:
            y = 200
        elif x < 160:
            y = 200 - 2 * (x - 80)                       # 2 rows per column
        elif x < 180:
            y = 40 + 4 * (x - 160)                       # falls 4 rows per column
        else:
            y = 120
        pts.append(float(y))
    return pts


class OnARamp(unittest.TestCase):
    def setUp(self):
        self.pts = rise_peak_fall()
        self.sub = stroke(self.pts)
        self.true = np.array([(self.pts[c] + self.pts[c + 1]) / 2 for c in range(len(self.pts) - 1)])

    def test_the_old_envelope_zigzags_on_a_ramp(self):
        py = ar.curve_positions(self.sub)                 # envelope=True, as shipped
        err = np.abs(py[85:155] - self.true[85:155])
        self.assertGreater(err.max(), 0.9, "the bug this mode exists for")

    def test_turns_follows_the_ramp(self):
        py = ar.curve_positions(self.sub, envelope="turns")
        err = np.abs(py[85:155] - self.true[85:155])
        self.assertLess(err.max(), 0.75, f"worst {err.max():.2f} rows off the climb")
        d = np.diff(py[85:155])
        self.assertTrue((d <= 0.5).all(), "the climb never steps backwards")

    def test_turns_keeps_the_peak(self):
        py = ar.curve_positions(self.sub, envelope="turns")
        self.assertLessEqual(np.nanmin(py[150:175]), 41.0,
                             "the peak is read at its top, not cut off")

    def test_flat_stretches_are_identical_either_way(self):
        a = ar.curve_positions(self.sub)
        b = ar.curve_positions(self.sub, envelope="turns")
        self.assertTrue(np.array_equal(a[:75], b[:75]))
        self.assertTrue(np.array_equal(a[190:], b[190:]))


class OtherModesUnchanged(unittest.TestCase):
    def test_true_and_false_are_what_they_were(self):
        sub = stroke(rise_peak_fall())
        a = ar.curve_positions(sub, envelope=True)
        b = ar.curve_positions(sub)
        self.assertTrue(np.array_equal(a, b))
        c = ar.curve_positions(sub, envelope=False)
        self.assertFalse(np.array_equal(a, c))


if __name__ == "__main__":
    unittest.main()
