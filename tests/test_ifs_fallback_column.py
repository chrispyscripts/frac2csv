"""Treating Pressure read against the RATE ladder, and why (#712).

  python3 -m unittest tests.test_ifs_fallback_column

Found while verifying #695, on pages that are not in Carmine's reports. On
v1.11.24:

  AER-Frac-Montney-ARC/00218-105040806505W600_0496118_COMP.pdf
    p328   Tr Press   0.22..18.21   axis reported (5.0, 15.0)
    p333   Tr Press   0.11..17.71   axis reported (5.0, 15.0)
    p363   Tr Press   5.30..18.79   axis reported (5.0, 15.0)

Every one of those sheets prints Treating Pressure on a 0..100 MPa ladder
and draws it reaching about 74. A peak OUTSIDE the axis the same code
reports for it is this project's clearest tell that something not on the
curve is being read as data — the `lim` band's own comment says so — and
here it is the axis that is wrong, not the peak. 18.21 is 74 MPa expressed
as a fraction of the RATE ladder, which the page rules 0..25 at the frame
and labels to 20: 74 x 25/100 = 18.5.

This is pre-existing and v1.11.24 did not cause it. The same pages read
1.54..15.15 at 17.7% present before, on the SAME wrong scale — the old clip
band was throwing most of the curve away. The frame-based clip recovered the
rest, so the page now exports ~100% of a wrongly-scaled channel instead of a
sixth of one. The fix made the defect fully visible; it did not make it.

TWO THINGS ARE WRONG, one under the other.

1. A TRAILING SPECK IS NOT A DIGIT. OCR glues the tick mark onto the label,
   and #709/#711 taught _axis_columns to strip it off the FRONT — "+18" for
   18, "~900" for 900. On 00218 p328 it is glued to the BACK. The pressure
   ladder is read almost whole, eleven spans at cx 94..102:

     '100' 164.52   '90-' 195.12   '80-' 225.72   '70-5' 256.32
     '60-' 286.92   '50-' 317.52   '40-' 348.12   '30'   378.54
     '20-' 409.32   '10-' 439.92   and '35.2', the section number, at 80.10

   Nine of the ten real ticks carry a trailing "-", fail the numeric test
   and are not read at all. That leaves "100" and "30" — TWO labels, one
   short of the three an OCR'd column needs — so no column is built for the
   pressure ladder at all, on a page that prints it in full.

   The rule is now symmetric: one speck off either end, and what remains
   must be the whole label. It is strictly additive — the leading form is
   tried first, so every label the old rule repaired is repaired
   identically, and only spans that the old rule could not touch are
   offered to the new one. "70-5" is still refused, because a dash between
   two digits is not a speck and nine ticks are already a ladder; inventing
   the tenth would be guessing.

2. THE POSITIONAL FALLBACK MAY NOT TAKE A COLUMN ANOTHER LETTER OWNS.
   With A's ladder unread, "A" is not in `placed`, and execution reaches
   `mapping["A"] = columns[0]`. On p328 the only columns are the rate
   ladder at x 651.96 and the concentration ladder at x 689.77, and "B" is
   printed 3.6pt over the rate one and has already claimed it. The fallback
   handed A that same column, so Treating Pressure and Backside Pressure
   were read off B's axis — two axes on one ladder, which is the exact thing
   the nearest-letter rule above it exists to stop ("A COLUMN IS ONE AXIS").

   `columns[0]` is A's ladder only on a page where A's ladder was found.
   Where it was not, the fallback now declines, and a letter with no column
   maps to nothing — which is already this function's honest answer for
   every letter but A.

   Counted over the 273 charts these seven filings export, on origin/main:
   the fallback fires on 46 of them and columns[0] is ALREADY CLAIMED on
   31. Six of those 31 are the rate ladder above, which exports pressure
   at a quarter scale. The other 25 are the CONCENTRATION ladder — A takes
   a 0..1500 column already claimed by C, the pressures come back ~15x
   high, and the `lim` band (10..300) then deletes them, so the page loses
   two channels in silence. That is the #695 p181 story still happening on
   25 pages, and it is why fixing 1 shows up below as channels GAINED.
   With both changes the fallback fires on 44 and columns[0] is claimed on
   none of them.

Measured, whole-page, on 00218:

  p328 before  Tr Press   100.0%    0.22..18.21   on (5.0, 15.0)
               Backside   100.0%    2.64.. 4.62   on (5.0, 15.0)
       after   Tr Press   100.0%    0.89..75.91   on (10.0, 100.0)
               Backside   100.0%   10.97..19.23   on (10.0, 100.0)
  p333 before  Tr Press   100.0%    0.11..17.71 / Backside  3.72.. 4.63
       after   Tr Press   100.0%    0.42..73.84 / Backside 15.49..19.27
  p363 before  Tr Press   100.0%    5.30..18.79 / Backside  4.02.. 4.72
       after   Tr Press   100.0%   22.06..78.36 / Backside 16.72..19.66

Slurry Rate and the two proppant concentrations do not move on any of the
three: they were on their own ladders before and are on them after.

The "after" numbers are what the sheets print. p328's red curve plateaus
just over 70 and spikes to about 75 at 00:00 before the drop; its magenta
backside runs 11 up to a flat 19. Both are drawn against the printed
0..100, and the rate curve they were being read against peaks at 14.78 on
a 0..20 — which is why the wrong answer looked like a plausible rate.

AND THE PAGES THAT MUST NOT MOVE. "Peak above its own reported axis" has a
SECOND cause on this same file, and it is not a mis-mapping:

  - 00218 p318 reports Tr Press 0.65..80.18 against an axis of (10.0, 60.0).
    Nothing is mis-mapped. The fallback fires, but columns[0] there is at
    x 101.34 — LEFT of the frame the page rules at 112.01..673.85, five
    ticks reading 9.97..59.96, and no letter has claimed it. It is A's own
    pressure ladder and the fallback is right to take it. The page draws
    Treating Pressure peaking about 81 on a printed 0..100 and its own
    Global Event Log prints TP 61.28 at 07:08, which matches the curve.
    The VALUE was already correct; only meta.axes was short, because OCR
    read that ladder's 10..60 labels and stopped. Refusing a channel whose
    peak exceeds its reported axis would have deleted it.
  - 00973 p117 is the page the LEADING-strip rule was written for ("20",
    "+18", "1000", "~900"). Making the rule symmetric must not disturb it,
    and does not: every value is identical to the point, and only the
    reported tick extent grows as more of the same ladders are read.

Both are asserted below, because the cost of this fix is measured in what
it leaves alone.
"""
import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz                                                # noqa: E402

import halliburton_ifs as ifs                              # noqa: E402
import ocr_labels                                          # noqa: E402


def sp(t, cx, cy):
    """A black OCR'd span, as _spans hands one to the axis reader."""
    return {"t": t, "cx": cx, "cy": cy, "x0": 0.0, "x1": 0.0,
            "color": 0, "ocr": True}


def text_sp(t, cx, cy):
    """The same off a page that has its own text layer: no ocr flag."""
    return {"t": t, "cx": cx, "cy": cy, "x0": 0.0, "x1": 0.0, "color": 0}


# 00218 p328's plot frame and its pressure ladder, verbatim as _spans
# returns them. The page rules its floor at y 470.28.
P328_BOX = fitz.Rect(111.96, 164.88, 640.68, 470.28)
P328_PRESSURE = [
    sp("35.2", 83.70, 80.10), sp("100", 94.50, 164.52),
    sp("90-", 101.34, 195.12), sp("80-", 101.34, 225.72),
    sp("70-5", 101.34, 256.32), sp("60-", 101.34, 286.92),
    sp("50-", 101.34, 317.52), sp("40-", 101.16, 348.12),
    sp("30", 101.34, 378.54), sp("20-", 101.16, 409.32),
    sp("10-", 101.70, 439.92)]


class ATrailingSpeckIsNotADigit(unittest.TestCase):
    """00218 p328: the ladder the page prints, and the reader could not see."""

    def cols(self, spans=None, box=P328_BOX):
        return ifs._axis_columns([dict(s) for s in (spans or P328_PRESSURE)],
                                 box)

    def test_the_pressure_ladder_is_found_at_all(self):
        # before: nine of eleven spans failed the numeric test, "100" and
        # "30" were left, and two is below the three a column needs
        got = self.cols()
        self.assertEqual(len(got), 1, [(c["x"], c["n"]) for c in got])

    def test_it_is_read_as_the_printed_0_to_100(self):
        c = self.cols()[0]
        lo = c["a"] + c["b"] * c["y_lo"]
        hi = c["a"] + c["b"] * c["y_hi"]
        self.assertAlmostEqual(max(lo, hi), 100.0, delta=0.2)
        self.assertAlmostEqual(min(lo, hi), 10.0, delta=0.2)

    def test_and_it_reaches_zero_at_the_frame_the_page_rules(self):
        # the line the nine ticks fit runs to 0.06 at y 470.28, which is
        # where this page draws the bottom of its plot
        c = self.cols()[0]
        self.assertAlmostEqual(c["a"] + c["b"] * 470.28, 0.0, delta=0.2)

    def test_nine_ticks_not_ten_and_not_the_section_number(self):
        c = self.cols()[0]
        self.assertEqual(c["n"], 9)          # 100, 90..40, 30, 20, 10
        # "70-5" is a dash BETWEEN digits, which is not a speck, so it is
        # refused rather than repaired to 70
        self.assertGreater(abs((c["a"] + c["b"] * 256.32) - 70.0), 0.0)
        # and "35.2" at cy 80.10 would have to sit 300pt lower to be a tick
        self.assertGreater(abs((c["a"] + c["b"] * 80.10) - 35.2), 70.0)

    def test_the_two_clean_labels_alone_are_still_not_a_ladder(self):
        # the rule adds labels; it does not lower the bar. Without the nine
        # repaired ones this is the pair origin/main was left with.
        self.assertEqual(
            self.cols([s for s in P328_PRESSURE if s["t"] in ("100", "30")]),
            [])


class WhatTheTrailingRuleMayNotClaim(unittest.TestCase):
    """A speck is one or two characters on the end of a whole number."""

    def strip(self, t):
        """-> what the cleanup leaves of a single OCR'd span."""
        s = sp(t, 100.0, 200.0)
        ifs._axis_columns([s, sp("1", 100.0, 300.0), sp("2", 100.0, 400.0)],
                          None)
        return s["t"]

    def test_the_speck_comes_off(self):
        for raw, want in (("90-", "90"), ("80-", "80"), ("0.5)", "0.5"),
                          ("100}", "100"), ("20.0))", "20.0")):
            self.assertEqual(self.strip(raw), want, raw)

    def test_the_leading_form_still_wins_and_is_unchanged(self):
        # #709/#711's own cases: tried first, so these cannot change
        for raw, want in (("+18", "18"), ("~900", "900")):
            self.assertEqual(self.strip(raw), want, raw)

    def test_a_clock_and_a_date_are_not_ticks(self):
        for raw in ("23:10", "2021-02-06", "07:08:28"):
            self.assertEqual(self.strip(raw), raw)

    def test_digits_on_both_sides_of_the_speck_are_refused(self):
        # "70-5" is p328's own case; a repair here would have to choose
        # which half of the label to believe
        for raw in ("70-5", "1-2", "10.0.0"):
            self.assertEqual(self.strip(raw), raw)

    def test_a_label_that_is_all_speck_is_refused(self):
        # OCR returns "oo" and "—O" for a 0 it cannot resolve. Eight ticks
        # of nine is already a ladder; the ninth is not worth guessing.
        for raw in ("oo", "—O", "--", "()"):
            self.assertEqual(self.strip(raw), raw)

    def test_more_than_two_characters_is_not_a_speck(self):
        for raw in ("100abc", "20 m3/min"):
            self.assertEqual(self.strip(raw), raw)


# 00218 p328 as origin/main SAW it, which is the situation the fallback is
# asked to resolve: the pressure ladder unread, so the only columns are the
# rate ladder (three labels, 5..15) and the concentration ladder (fourteen,
# 100..1500), with a black "B" printed 3.6pt over the rate one.
def col(x, lo, hi, y_lo, y_hi, n):
    """A tick column as _axis_columns returns one."""
    b = (hi - lo) / (y_hi - y_lo)
    return {"x": x, "n": n, "a": lo - b * y_lo, "b": b,
            "y_lo": y_lo, "y_hi": y_hi}


P328_RATE_COL = col(651.96, 15.0, 5.0, 279.18, 406.80, 3)
P328_CONC_COL = col(689.77, 1500.0, 100.0, 164.52, 450.00, 14)
P328_LETTER_B = [sp("B", 655.56, 149.94)]


class TheFallbackMayNotTakeAClaimedColumn(unittest.TestCase):
    """00218 p328's mapping, with and without A's own ladder."""

    def test_a_gets_nothing_when_b_already_owns_the_only_left_column(self):
        # before: mapping["A"] = columns[0] — the rate ladder, which "B" is
        # printed over and has already claimed. Two axes, one ladder.
        got = ifs._map_axes(["A", "B", "C"],
                            [P328_RATE_COL, P328_CONC_COL],
                            list(P328_LETTER_B))
        self.assertNotIn("A", got)
        self.assertIs(got["B"], P328_RATE_COL)
        self.assertIs(got["C"], P328_CONC_COL)

    def test_a_still_gets_the_leftmost_column_when_nobody_claimed_it(self):
        # the case the fallback exists for, and the one 00218 p318 is: A's
        # own ladder is found, its letter is not read, and the fallback is
        # right to take it. 44 of the 273 charts swept rely on it, and the
        # guard must not touch them.
        press = col(101.34, 100.0, 10.0, 164.52, 439.92, 9)
        got = ifs._map_axes(["A", "B", "C"],
                            [press, P328_RATE_COL, P328_CONC_COL],
                            list(P328_LETTER_B))
        self.assertIs(got["A"], press)
        self.assertIs(got["B"], P328_RATE_COL)
        self.assertIs(got["C"], P328_CONC_COL)

    def test_no_column_is_ever_handed_to_two_letters(self):
        for cols in ([P328_RATE_COL, P328_CONC_COL],
                     [P328_CONC_COL],
                     [P328_RATE_COL]):
            got = ifs._map_axes(["A", "B", "C"], cols,
                                list(P328_LETTER_B))
            used = [id(c) for c in got.values()]
            self.assertEqual(len(used), len(set(used)), got)

    def test_a_letter_that_was_read_still_beats_position(self):
        # "B" is 3.6pt from the rate column and 34pt from the concentration
        # one; it takes the near one, and A does not get either
        got = ifs._map_axes(["A", "B"], [P328_RATE_COL, P328_CONC_COL],
                            list(P328_LETTER_B))
        self.assertIs(got["B"], P328_RATE_COL)
        self.assertNotIn("A", got)


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/"
                  "00218-105040806505W600_0496118_COMP.pdf")
BCER = glob.glob("/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/"
                 "00973-100131208122W602_41210_COMP_2021SEP24.pdf")

ALL_FIVE = ["BH Prop Conc", "Backside Pressure", "Slurry Rate", "Tr Press",
            "WH Prop Conc"]


def _read(page):
    """-> ({channel: (percent present, min, max)}, meta)."""
    meta, samples, data, info = ifs.extract_page(page)
    out = {}
    for k, v in data.items():
        v = np.asarray(v, float)
        f = v[np.isfinite(v)]
        out[k] = (round(100.0 * len(f) / max(1, len(v)), 1),
                  float(f.min()), float(f.max()))
    return out, meta


@unittest.skipUnless(DRIVE and ocr_labels.available(),
                     "the AER drive or tesseract is not here")
class OnTheRateLadderPages(unittest.TestCase):
    """00218 p328, p333 and p363, end to end."""

    @classmethod
    def setUpClass(cls):
        cls.doc = fitz.open(DRIVE[0])

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()

    def test_treating_pressure_is_on_the_0_to_100_ladder(self):
        for pno, peak in ((327, 75.91), (332, 73.84), (362, 78.36)):
            got, meta = _read(self.doc[pno])
            pct, lo, hi = got["Tr Press"]
            self.assertEqual(pct, 100.0, pno)
            self.assertAlmostEqual(hi, peak, delta=0.6, msg=str(pno))
            # was (5.0, 15.0) — the rate ladder's own tick extent
            self.assertAlmostEqual(meta.axes["Tr Press"][1], 100.0, delta=0.5,
                                   msg=str(pno))

    def test_backside_pressure_comes_back_as_a_pressure(self):
        # a backside that sits flat at 19 MPa, not at 4.6
        for pno, lo_, hi_ in ((327, 10.97, 19.23), (332, 15.49, 19.27),
                              (362, 16.72, 19.66)):
            got, _meta = _read(self.doc[pno])
            pct, lo, hi = got["Backside Pressure"]
            self.assertEqual(pct, 100.0, pno)
            self.assertAlmostEqual(lo, lo_, delta=0.6, msg=str(pno))
            self.assertAlmostEqual(hi, hi_, delta=0.6, msg=str(pno))

    def test_no_channel_was_lost_to_get_there(self):
        for pno in (327, 332, 362):
            got, _meta = _read(self.doc[pno])
            self.assertEqual(sorted(got), ALL_FIVE, pno)

    def test_the_three_channels_that_were_right_did_not_move(self):
        # Slurry Rate is B's, both concentrations are C's, and all three
        # were mapped by their own printed letter before and after
        for pno, rate, conc in ((327, 14.78, 494.21), (332, 14.95, 570.63),
                                (362, 15.11, 511.52)):
            got, meta = _read(self.doc[pno])
            self.assertAlmostEqual(got["Slurry Rate"][2], rate, delta=0.2,
                                   msg=str(pno))
            self.assertAlmostEqual(got["WH Prop Conc"][2], conc, delta=3.0,
                                   msg=str(pno))
            self.assertAlmostEqual(meta.axes["Slurry Rate"][1], 15.0,
                                   delta=0.2, msg=str(pno))
            self.assertAlmostEqual(meta.axes["WH Prop Conc"][1], 1500.0,
                                   delta=5.0, msg=str(pno))

    def test_no_two_axis_letters_share_a_ladder(self):
        # the invariant the fallback was breaking: A and B cannot both be
        # the rate ladder. Read off meta.axes, which is per channel.
        for pno in (327, 332, 362):
            _got, meta = _read(self.doc[pno])
            press = meta.axes["Tr Press"]
            rate = meta.axes["Slurry Rate"]
            self.assertNotAlmostEqual(press[1], rate[1], delta=1.0,
                                      msg=str(pno))


@unittest.skipUnless(DRIVE and ocr_labels.available(),
                     "the AER drive or tesseract is not here")
class ThePageThatWasAlreadyRight(unittest.TestCase):
    """00218 p318: the fallback firing onto A's OWN ladder, which is fine."""

    @classmethod
    def setUpClass(cls):
        cls.doc = fitz.open(DRIVE[0])

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()

    def test_treating_pressure_keeps_the_peak_the_page_draws(self):
        # 80.18 before, against a printed 0..100 the curve really does
        # touch at about 81 just before 06:00
        got, _meta = _read(self.doc[317])
        self.assertEqual(sorted(got), ALL_FIVE)
        self.assertAlmostEqual(got["Tr Press"][2], 80.18, delta=0.3)
        self.assertAlmostEqual(got["Backside Pressure"][2], 19.23, delta=0.3)

    def test_and_its_reported_axis_stops_being_short(self):
        # the ladder is printed 0..100 and OCR read it to 60; reading more
        # of the same ladder moves the reported extent, not the values
        _got, meta = _read(self.doc[317])
        self.assertGreaterEqual(meta.axes["Tr Press"][1], 85.0)


@unittest.skipUnless(BCER and ocr_labels.available(),
                     "the BCER drive or tesseract is not here")
class TheLeadingStripPageIsUndisturbed(unittest.TestCase):
    """00973 p117, the page #709/#711 was written for."""

    def test_every_value_is_what_it_was(self):
        doc = fitz.open(BCER[0])
        got, meta = _read(doc[116])
        doc.close()
        self.assertEqual(sorted(got),
                         ["BHProppant Conc", "Slurry Rate", "Tr Press",
                          "WH Prop Conc"])
        for k, lo_, hi_ in (("Tr Press", 0.64, 70.16),
                            ("Slurry Rate", -0.01, 12.08),
                            ("WH Prop Conc", -0.52, 518.18),
                            ("BHProppant Conc", -0.52, 518.59)):
            pct, lo, hi = got[k]
            self.assertEqual(pct, 100.0, k)
            self.assertAlmostEqual(lo, lo_, delta=0.05, msg=k)
            self.assertAlmostEqual(hi, hi_, delta=0.05, msg=k)


if __name__ == "__main__":
    unittest.main()
