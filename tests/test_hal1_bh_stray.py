"""The crimson pen's palest fringe no longer sets the BH Prop Conc peak.

#702-#704 cut the crimson Treating Pressure ink out of the purple BH Prop
Conc mask on the red family (see hal1._bh_conc, and tests/test_hal1_bh_ink).
That takes the pen's CORE. What it cannot reach is the pale anti-aliased edge
of the same stroke — (255, 216, 242) and (255, 218, 241), one and two rows off
a core of (155, 27, 62) — which fails the red family's r > b + m1 test and
stays in the mask.

The page where that still cost a number is

  AER-Frac-Montney-ARC/00423-100113306204W600_0503461_COMP.pdf, page 308
  (0-based; "Treatment Interval 3")

whose BH Prop Conc read a 31-second island at 1155.9 kg/m3 — 15x the chart's
77.3 MPa treating pressure, both axes coming off the same two frame rows
(1500.0..0.46 for concentration against 100.0..0.07 for pressure), so the
island is the pressure stroke and not proppant. 31 samples of 5547, but the
highest in the channel, so it set the per-channel peak the project reports.

Fourteen fringe columns reach _drop_orphans on that page and twelve go.
Plot columns 190 and 194 do not: 194 is seven columns from 201, where the
purple pen's own ink resumes on the bottom rule, so the run-length test sees
one long cluster. curve_positions' spike guard misses them too, because
through the pad the purple pen draws nothing but that rule and four of the
seven finite columns in its 31-wide window ARE the strays — the reference it
computes, 186, is a stray's own row, 27 rows from the stray where the guard
wants 83.

hal1._clean_track alternates the orphan pass with auto_raster's own spike
test until neither moves. On the real page that drops plot columns 190 and
194 and nothing else — 717 finite columns to 715, 5547 exported samples to
5516 — and the chart's BH Prop Conc peak comes back to 407.16 kg/m3.

  python3 -m unittest tests.test_hal1_bh_stray
"""
import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_raster as ar                                   # noqa: E402
import hal1                                                # noqa: E402

H, W = 693, 270          # the real plot is 693 x 1042; this is its pad half

# Plot columns 201..261 of 00423 p308, where the purple pen is resting on the
# bottom rule and nothing else: the ranges below are the page's own, gaps and
# all, because it is the gaps that leave the strays looking like company.
FLOOR = [(201, 203), (211, 236), (244, 251), (257, 261)]

# The crimson stroke's pale fringe, (plot column, plot row), read off the same
# page. Column 190 carries two pixels and the rest one; none of them is more
# than two rows tall, so every one is a short run as far as the spike test is
# concerned.
FRINGE = [(76, 180), (81, 174), (89, 150), (97, 148), (107, 193), (108, 193),
          (113, 180), (127, 181), (128, 167), (147, 182), (158, 196),
          (168, 186), (189, 160), (190, 159), (194, 162), (205, 186),
          (209, 188)]

DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/AER-Frac-*/"
                  "00423-100113306204W600_0503461_COMP.pdf")


def pad_mask():
    """The BH Prop Conc mask through interval 3's pad, column for column."""
    sub = np.zeros((H, W), bool)
    for a, b in FLOOR:
        sub[691:693, a:b + 1] = True
    for cx, row in FRINGE:
        sub[row, cx] = True
    sub[155, 190] = True                # the one column with two fringe pixels
    return sub


def floor_columns():
    return [c for a, b in FLOOR for c in range(a, b + 1)]


class TheFringeStops(unittest.TestCase):

    def test_the_orphan_pass_alone_keeps_two_of_them(self):
        """The fault, stated as a measurement: 190 and 194 survive.

        Everything else the fringe left is isolated enough for one test or the
        other. These two are not, and they read at the top of the plot.
        """
        sub = pad_mask()
        py = hal1._drop_orphans(ar.curve_positions(sub))
        self.assertTrue(np.isfinite(py[190]))
        self.assertTrue(np.isfinite(py[194]))
        self.assertLess(float(np.nanmin(py)), 200.0)   # rows, so near the top
        # and they are the ONLY survivors above the rule: the rest went
        others = [c for c, _r in FRINGE if c not in (190, 194)]
        self.assertFalse(np.isfinite(py[others]).any())

    def test_looking_again_with_a_clean_reference_removes_them(self):
        sub = pad_mask()
        py = hal1._clean_track(sub, ar.curve_positions(sub))
        self.assertFalse(np.isfinite(py[190]))
        self.assertFalse(np.isfinite(py[194]))
        # nothing above the bottom rule is left
        self.assertGreater(float(np.nanmin(py)), 600.0)

    def test_it_takes_none_of_the_pen_resting_on_the_rule(self):
        """The cost side. Through the pad the purple pen IS one or two pixels.

        That is why a thinness rule cannot be used here: it would delete the
        trace it is meant to protect.
        """
        sub = pad_mask()
        cols = floor_columns()
        before = ar.curve_positions(sub)
        after = hal1._clean_track(sub, before.copy())
        self.assertEqual(int(np.isfinite(after[cols]).sum()), len(cols))
        self.assertTrue(np.array_equal(np.isfinite(before[cols]),
                                       np.isfinite(after[cols])))

    def test_a_near_vertical_move_is_not_a_stray(self):
        """A real plunge is a TALL run, and auto_raster's SPIKE_RUN keeps it.

        The proppant ramp ending is exactly this: one column of ink spanning
        most of the drop. Without the height test the pass would eat it.
        """
        sub = np.zeros((H, W), bool)
        sub[100:103, 0:150] = True                  # the pen, held high
        sub[100:660, 150] = True                    # one column, straight down
        sub[657:660, 151:W] = True                  # and held low after
        py = hal1._clean_track(sub, ar.curve_positions(sub))
        self.assertTrue(np.isfinite(py[150]))
        self.assertEqual(int(np.isfinite(py).sum()), W)


@unittest.skipUnless(DRIVE, "the AER drive is not mounted")
class ThePageItself(unittest.TestCase):

    def test_00423_page_308_peaks_at_the_purple_pen(self):
        import fitz
        page = fitz.open(DRIVE[0])[308]
        self.assertTrue(hal1.detect(page))
        meta, _samples, channels, _info = hal1.extract_page(page)
        self.assertEqual(meta["stage"], 3)
        bh = next(c for c in channels if c["label"] == "BH Prop Conc")
        v = np.asarray(bh["values"], float)
        self.assertAlmostEqual(float(np.nanmax(v)), 407.16, delta=0.05)
        self.assertEqual(int(np.isfinite(v).sum()), 5516)


if __name__ == "__main__":
    unittest.main()
