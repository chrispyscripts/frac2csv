"""A conc-axis title the render broke into pieces is still furniture (#716).

#70/#71 cleared the rotated "Conc. [kg/m3]" title on the CLEAN sideways
render, where it arrives as one island of six or seven columns and the ink
vote carries it (tests/test_hal_turned_title). This is the half of #716 that
survived that, on the lightly-rendered pages of

  BCER-Frac/Spud-2019-2023/01367-103133407818W600_43621_COMP_2023FEB09.pdf

which prints the same title, in the same pale chocolate, at the same place on
the template as its own page 266 does -- plot columns 51..64, rows 300..392,
right down to a single pixel at column 52 row 307 that is on all five pages
looked at here. Page 266 renders it cleanly. Page 188 lays grey vertical
gridlines over the whole chart, and pages 200, 221 and 260 run the crimson
pressure pen straight down through the lettering; either way most of the glyph
blends out of the chocolate cut and what reaches _furniture_cols is wreckage.

On page 188 it is FOUR islands -- 51..52, 54..59, 62..62, 64..64 -- twenty lit
pixels over ten columns, five of those columns holding a single pixel. A column
with one pixel has a span of one, so it can never be "hollow": one column of
the ten qualifies as sparse and page 221 raises none at all. The count vote
wants a majority of columns and the ink vote a majority of the ink, and 1-of-10
and 3-of-20 are neither, however the fragments are cut or merged.

What it cost, page by page (Slurry Prop Conc peaks in kg/m3, against a BH
Prop Conc on the same charts that peaks 252..464):

  page 188  (interval  1)   835.65 -> 223.49   607 samples -> 563, 17.1% -> 15.8%
  page 200  (interval  5)   906.86 -> 390.03   5650 -> 5555
  page 221  (interval 12)   832.81 -> 461.36   4105 -> 4058
  page 260  (interval 25)   850.13 -> 467.69   3375 -> 3322
  page 266  (interval 27)   495.38 -> 495.38   the clean render, untouched

Page 188 is the one #716 was reported on, and it took two changes to reach.
The grey gridlines that break its title also run through its concentration
TICK LABELS, and f8ae686 (#715) is what got the ladder read at all -- before
it, tesseract returned nothing from that strip and BOTH concentration
channels were dropped with "axis unreadable" on a page whose curves are drawn
and traceable. That put the channel on the page; this puts the right numbers
in it. On b8076eb the page reads 10.60..835.65 at 17.1% present, and with the
title cleared 10.60..223.49 at 15.8%: 44 samples of 607, and nothing else on
the page moves by a digit.

That island is the shape of the whole family: 44 consecutive samples reading
680..836 where every other run on that channel sits between 10 and 224, with
159 columns of blank page between it and the channel's next ink -- wider than
curve_trace.resample will bridge, so it was already a detached island in the
export and its only effect was to set the peak.

The vote added for it does not look at the pieces at all. It merges the
band's ink across the gaps a light render opens inside one glyph and weighs
the group's ink against the ROWS IT REACHES: a pen that travels 78 rows lays
down at least 78 pixels, because a stroke is connected, and this group holds
20.

Where it stops is tight, and the tests below pin both sides of it. Ink per row
reached runs 0.08..0.45 over the 17 groups it clears on 01366, 01367, 00413
and 00423; 0.59 / 0.59 / 0.66 over the three titles the ink vote already
clears (00413 p248, 01367 p266, 00423 p360); and 0.50..0.74 over the titles
nothing here reaches. That last set overlaps the pages this must not touch,
0.59 against 0.59, so the bar cannot be raised to take them in.

  python3 -m unittest tests.test_hal_light_title
"""
import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hal1                                                # noqa: E402

H, W = 693, 1042        # the plot rect on every page: (62, 74, 1104, 767)

# Every lit pixel of the chocolate mask in the first 83 columns of 01367 p188,
# read off the page. Ten columns, twenty pixels, rows 303..380.
BROKEN = {51: (306, 309), 52: (307,), 54: (309,),
          55: (374, 375, 376, 377, 379), 56: (377, 380),
          57: (303, 326, 368), 58: (342, 343, 345), 59: (347,),
          62: (328,), 64: (329,)}

# The same title on the same file's page 266, which renders cleanly: one
# island at 55..61 holding 46 of the 47 pixels, plus that same lone pixel at
# column 52 row 307. This is what the ink vote was written for and it must go
# on being what decides this page.
CLEAN = {52: (307,),
         55: (374, 375, 379), 56: (374, 375, 377, 378, 379),
         57: (301, 302, 326, 327, 330, 342, 343, 344, 365, 366, 367,
              374, 375, 377),
         58: (301, 302, 326, 327, 330, 342, 343, 366, 367, 374, 375),
         59: (326, 327, 328, 364, 365, 366, 367, 374),
         60: (364, 365, 366), 61: (364, 365)}

# 00423 p314's BH concentration climbing out of the floor inside the same band,
# the fixture tests/test_hal_turned_title protects: (column, first row, last
# row, lit pixels). Nine of its 24 columns are hollow and hold 440 of its 615
# pixels. It stands on the bottom rule, and that is the only thing that tells
# it from decoration -- so the new vote has to be shown not to reach it either.
RISE = [(57, 534, 549, 16), (58, 534, 539, 6), (59, 486, 517, 32),
        (60, 470, 692, 49), (61, 403, 692, 85), (62, 388, 692, 45),
        (63, 262, 692, 85), (64, 246, 692, 82), (65, 214, 692, 49),
        (66, 214, 245, 32), (67, 182, 197, 16), (68, 182, 197, 16),
        (69, 153, 692, 14), (70, 154, 692, 13), (71, 691, 692, 2),
        (72, 182, 692, 18), (73, 182, 189, 8), (74, 177, 188, 6),
        (75, 166, 181, 16), (76, 166, 178, 13), (77, 163, 165, 3),
        (78, 162, 165, 4), (79, 163, 165, 3), (80, 164, 165, 2)]


def _mask(pixels, trace_from):
    sub = np.zeros((H, W), bool)
    for col, rows in pixels.items():
        for r in rows:
            sub[r, col] = True
    sub[600:604, trace_from:900] = True     # the trace, right of the band
    return sub


def broken_mask():
    """01367 p188's chocolate band: the title in four pieces, and no more."""
    return _mask(BROKEN, 223)               # p188's next chocolate ink


def clean_mask():
    """01367 p266's, for comparison: the same title, rendered whole."""
    return _mask(CLEAN, 160)


def rise_mask():
    sub = np.zeros((H, W), bool)
    for c, top, bot, n in RISE:
        rows = np.unique(np.linspace(top, bot, n).round().astype(int))
        sub[rows, c] = True
    sub[100:104, 90:900] = True
    return sub


class TheBrokenTitle(unittest.TestCase):

    def test_why_both_older_votes_miss_it(self):
        """The fault, as a measurement: one sparse column of ten."""
        sub = broken_mask()
        tall = hal1.FURNITURE_SPAN * H
        hollow = []
        for c in range(int(hal1.FURNITURE_BAND * W)):
            ys = np.flatnonzero(sub[:, c])
            if len(ys) < 2:
                continue
            span = ys[-1] - ys[0] + 1
            if span > tall and len(ys) < hal1.FURNITURE_FILL * span:
                hollow.append(c)
        self.assertEqual(hollow, [57])
        lit = sorted(BROKEN)
        self.assertEqual(len(lit), 10)
        self.assertEqual(int(sub[:, :83].sum()), 20)
        # five of the ten hold a single pixel, so they have no span to test
        self.assertEqual(sum(1 for c in lit if len(BROKEN[c]) == 1), 5)
        # the count vote: 1 of 10.  the ink vote: 3 of 20.  neither is a half.
        self.assertLess(len(hollow) * 2, len(lit))
        self.assertLess(int(sub[:, hollow].sum()) * 2, 20)

    def test_it_is_four_islands_and_merging_them_does_not_help(self):
        """Why rejoining the fragments and asking again is not the answer.

        It was tried. Both of the older votes are majorities, and the merged
        group is one sparse column of ten holding three pixels of twenty --
        so neither carries, and the merge only widens what a wrong answer
        would swallow.
        """
        sub = broken_mask()
        idx = np.flatnonzero(sub[:, :83].any(axis=0))
        runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
        self.assertEqual([(int(r[0]), int(r[-1])) for r in runs],
                         [(51, 52), (54, 59), (62, 62), (64, 64)])
        merged = np.split(idx, np.flatnonzero(
            np.diff(idx) > hal1.FURNITURE_GAP) + 1)
        self.assertEqual(len(merged), 1)
        grp = merged[0]
        self.assertEqual((int(grp[0]), int(grp[-1])), (51, 64))
        ink = sub.sum(axis=0)
        self.assertEqual((len(grp), int(ink[grp].sum())), (10, 20))
        self.assertEqual(int(ink[[57]].sum()), 3)     # the one sparse column
        self.assertLess(1 * 2, len(grp))              # the count vote, merged
        self.assertLess(3 * 2, int(ink[grp].sum()))   # the ink vote, merged

    def test_the_group_reaches_further_than_its_ink_can_draw(self):
        """The evidence the new vote runs on, stated before it is used."""
        sub = broken_mask()
        rows = np.flatnonzero(sub[:, 51:65].any(axis=1))
        reach = int(rows[-1] - rows[0] + 1)
        self.assertEqual((int(rows[0]), int(rows[-1])), (303, 380))
        self.assertEqual(reach, 78)
        self.assertEqual(int(sub[:, 51:65].sum()), 20)
        # a connected stroke crossing 78 rows cannot hold fewer than 78 pixels
        self.assertLess(20, hal1.FURNITURE_FILL * reach)
        self.assertGreater(reach, hal1.FURNITURE_SPAN * H)
        self.assertLess(int(rows[-1]), H - hal1.FURNITURE_SPAN * H)

    def test_every_column_of_the_broken_title_is_cleared(self):
        junk = hal1._furniture_cols(broken_mask())
        self.assertEqual(np.flatnonzero(junk).tolist(), sorted(BROKEN))

    def test_the_trace_past_the_band_is_untouched(self):
        junk = hal1._furniture_cols(broken_mask())
        self.assertFalse(junk[83:].any())

    def test_the_clean_render_is_still_decided_by_the_ink_vote(self):
        """p266 holds 47 px over 79 rows, 0.59 a row: the new vote passes.

        It is the ink vote that clears 55..61 there, exactly as before, and the
        lone pixel at column 52 is left for _drop_orphans as it always was.
        """
        sub = clean_mask()
        rows = np.flatnonzero(sub[:, 52:62].any(axis=1))
        reach = float(rows[-1] - rows[0] + 1)
        self.assertEqual((int(rows[0]), int(rows[-1])), (301, 379))
        self.assertEqual(int(sub[:, 52:62].sum()), 47)
        self.assertGreater(47, hal1.FURNITURE_FILL * reach)     # 47 vs 39.5
        self.assertEqual(np.flatnonzero(hal1._furniture_cols(sub)).tolist(),
                         [55, 56, 57, 58, 59, 60, 61])

    def test_a_rise_out_of_the_floor_is_still_not_furniture(self):
        """The new vote keeps the floor test: 00423 p314 is out of reach.

        Merged, that rise is 24 columns reaching 540 rows -- taller and no less
        continuous-looking than the title -- and it holds 615 pixels, 1.14 for
        every row it crosses. Both halves of the test refuse it.
        """
        sub = rise_mask()
        rows = np.flatnonzero(sub[:, 57:81].any(axis=1))
        reach = float(rows[-1] - rows[0] + 1)
        self.assertEqual((int(rows[0]), int(rows[-1])), (153, 692))
        self.assertEqual(int(sub[:, 57:81].sum()), 615)
        self.assertGreater(615, hal1.FURNITURE_FILL * reach)
        self.assertGreaterEqual(int(rows[-1]), H - hal1.FURNITURE_SPAN * H)
        self.assertFalse(hal1._furniture_cols(sub).any())

    def test_a_steep_early_trace_inside_the_band_survives(self):
        """The cost side: a real pen climbing in the band is dense, not sparse.

        Three columns straight up through 400 rows, clear of the floor and
        wholly inside the band -- the one shape this vote could plausibly
        mistake for lettering. It holds one pixel per row and is kept.
        """
        sub = np.zeros((H, W), bool)
        sub[200:600, 60:63] = True
        junk = hal1._furniture_cols(sub)
        self.assertFalse(junk.any())


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/BCER-Frac/*/"
                  "01367-103133407818W600_43621_COMP_2023FEB09.pdf")

# (page, Treatment Interval, the peak with the title cleared). What each read
# on b8076eb, in the same order: 835.65, 906.86, 832.81, 850.13 and 495.38 --
# the last of those is page 266, the clean render, which is here to say that
# this changes nothing about the page the ink vote already handled.
PAGES = [(188, 1, 223.49), (200, 5, 390.03), (221, 12, 461.36),
         (260, 25, 467.69), (266, 27, 495.38)]


@unittest.skipUnless(DRIVE, "the BCER drive is not mounted")
class OnThePage(unittest.TestCase):

    def test_no_page_reports_a_conc_above_its_own_chart(self):
        import fitz
        doc = fitz.open(DRIVE[0])
        try:
            for page_no, interval, now in PAGES:
                meta, _, channels, _ = hal1.extract_page(doc[page_no - 1])
                self.assertEqual(meta["stage"], interval)
                by = {c["label"]: c for c in channels}
                self.assertIn("Slurry Prop Conc", by)
                got = float(np.nanmax(by["Slurry Prop Conc"]["values"]))
                self.assertAlmostEqual(got, now, delta=0.5)
                # and it is no longer two and a half times the BH pen beside it
                bh = float(np.nanmax(by["BH Prop Conc"]["values"]))
                self.assertLess(got, bh * 1.2)
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
