"""The conc-axis title is furniture on a SIDEWAYS treatment plot too (#70, #71).

00413 p247 "Treatment Interval 18" and 00423 p359 "Treatment Interval 20" are
both the turned Halliburton render, read through np.rot90(img, -1). The
rotated "Conc. [kg/m3]" title lands inside the frame in the series' own
chocolate, and _furniture_cols missed it by one column: of the six columns it
occupies only 57, 58 and 59 run the glyph's full height, and three of six is
not a majority. Slurry Prop Conc then peaked at 828.67 kg/m3 on 00413 and
828.65 on 00423 -- the same phantom on two unrelated wells -- against a
printed trace that plateaus just under 600. With the title cleared they read
575.8 and 569.6.

  python3 -m unittest tests.test_hal_turned_title
"""
import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hal1                                                # noqa: E402

H, W = 693, 1042          # the plot rect on both pages: (62, 74, 1104, 767)

# Every lit pixel of the chocolate mask in the first 83 columns of 00413 p247,
# read off the page: the rotated "Conc. [kg/m3]" title, and one stray at 52.
TITLE = {301: (57, 58), 302: (57, 58), 307: (52,),
         326: (57, 58, 59), 327: (57, 58, 59), 328: (59,),
         330: (57, 58), 342: (57, 58), 343: (57, 58), 344: (57,),
         366: (58,), 367: (58,), 369: (58,), 370: (58,),
         374: (55, 56, 59, 60), 375: (55, 56, 59, 60), 376: (58, 59),
         377: (55, 56, 58, 59, 60), 378: (56, 58, 59, 60),
         379: (55, 56, 59, 60), 380: (59,), 383: (57, 58)}

# The BH concentration on 00423 p314 climbs out of the floor inside the same
# band: (column, first row, last row, lit pixels) as measured there. Nine of
# its 24 columns are hollow and they hold 440 of its 615 pixels, so the ink
# alone would condemn it -- it survives because it still stands on the floor.
RISE = [(57, 534, 549, 16), (58, 534, 539, 6), (59, 486, 517, 32),
        (60, 470, 692, 49), (61, 403, 692, 85), (62, 388, 692, 45),
        (63, 262, 692, 85), (64, 246, 692, 82), (65, 214, 692, 49),
        (66, 214, 245, 32), (67, 182, 197, 16), (68, 182, 197, 16),
        (69, 153, 692, 14), (70, 154, 692, 13), (71, 691, 692, 2),
        (72, 182, 692, 18), (73, 182, 189, 8), (74, 177, 188, 6),
        (75, 166, 181, 16), (76, 166, 178, 13), (77, 163, 165, 3),
        (78, 162, 165, 4), (79, 163, 165, 3), (80, 164, 165, 2)]


def title_mask():
    sub = np.zeros((H, W), bool)
    for row, cols in TITLE.items():
        for c in cols:
            sub[row, c] = True
    sub[600:604, 130:900] = True          # the trace itself, well right of the band
    return sub


def rise_mask():
    """A column-for-column stand-in for 00423 p314's BH concentration."""
    sub = np.zeros((H, W), bool)
    for c, top, bot, n in RISE:
        rows = np.unique(np.linspace(top, bot, n).round().astype(int))
        sub[rows, c] = True
    sub[100:104, 90:900] = True           # the rest of the trace, past the band
    return sub


class TheTurnedTitle(unittest.TestCase):

    def test_the_island_is_three_hollow_columns_of_six(self):
        """Why the count vote failed: it is short by exactly one column."""
        sub = title_mask()
        tall = hal1.FURNITURE_SPAN * H
        hollow = []
        for c in range(55, 61):
            ys = np.flatnonzero(sub[:, c])
            span = ys[-1] - ys[0] + 1
            if span > tall and len(ys) < hal1.FURNITURE_FILL * span:
                hollow.append(c)
        self.assertEqual(hollow, [57, 58, 59])
        # and why the ink vote carries it: those three hold most of the island
        self.assertEqual(int(sub[:, 55:61].sum()), 48)
        self.assertEqual(int(sub[:, hollow].sum()), 34)

    def test_the_title_is_cleared(self):
        junk = hal1._furniture_cols(title_mask())
        self.assertEqual(np.flatnonzero(junk).tolist(), [55, 56, 57, 58, 59, 60])

    def test_the_trace_past_the_band_is_untouched(self):
        junk = hal1._furniture_cols(title_mask())
        self.assertFalse(junk[83:].any())

    def test_a_rise_out_of_the_floor_is_not_furniture(self):
        """Most of its ink is hollow too -- the floor is what tells them apart."""
        sub = rise_mask()
        tall = hal1.FURNITURE_SPAN * H
        run = np.arange(57, 81)
        ink = sub.sum(axis=0)
        hollow = []
        for c in run:
            ys = np.flatnonzero(sub[:, c])
            span = ys[-1] - ys[0] + 1
            if span > tall and len(ys) < hal1.FURNITURE_FILL * span:
                hollow.append(c)
        # the ink vote would condemn it, so this really does test the floor
        self.assertEqual(len(hollow), 9)
        self.assertEqual((int(ink[hollow].sum()), int(ink[run].sum())), (440, 615))
        self.assertGreater(ink[hollow].sum() * 2, ink[run].sum())
        self.assertFalse(hal1._furniture_cols(sub).any())


DRIVE = "/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/__HAL"
PAGES = [("00413-100012606306W600_0503297_COMP.pdf", 247, 18, 575.8),
         ("00423-100113306204W600_0503461_COMP.pdf", 359, 20, 569.6)]


@unittest.skipUnless(os.path.isdir(DRIVE), "the AER drive is not mounted")
class OnThePage(unittest.TestCase):

    def test_neither_turned_page_reports_the_828_phantom(self):
        import fitz
        for name, page_no, interval, peak in PAGES:
            hit = glob.glob(os.path.join(DRIVE, name))
            self.assertTrue(hit, name)
            doc = fitz.open(hit[0])
            meta, _, channels, _ = hal1.extract_page(doc[page_no])
            self.assertEqual(meta["stage"], interval)
            conc = [c for c in channels if c["label"] == "Slurry Prop Conc"]
            self.assertEqual(len(conc), 1, name)
            got = float(np.nanmax(conc[0]["values"]))
            self.assertAlmostEqual(got, peak, delta=0.2)
            self.assertLess(got, 600.0)   # the printed trace plateaus under 600
            doc.close()


if __name__ == "__main__":
    unittest.main()
