"""The IFS chart read against the ladder it is actually drawn on (#695).

  python3 -m unittest tests.test_ifs_wrong_axis

Carmine: "most charts not extracting data, this example stage the TR pressure
goes off the y axis". The example is

  AER-Frac-Montney-ARC/00217-105130506505W602_0496117_COMP.pdf, page 323
  (1-based; "35.2  Interval 35 - Entire Treatment")

and the pressure is not going off its axis. It is being read off SOMEBODY
ELSE'S. The page prints three ladders — A 0..100 MPa on the left, B 0..20
m3/min and C 0..1500 kg/m3 on the right — and carries no text layer, so every
label is OCR'd. Four separate rules each threw a ladder or a channel away,
and what was left collected whatever had nowhere else to go.

1. AN AXIS IS A LINE, NOT AN ARITHMETIC SEQUENCE. p323's pressure ladder is
   printed every 10 MPa and OCR read four of its eleven labels: 100 at
   cy 137.88, 60 at 270.90, 30 at 370.62 and 0 at 470.34. Those four sit on
   one line to within 0.1pt — 0.3008 MPa per point — but they step 40, 30,
   30, so no constant-gap chain links them and the only arithmetic run is
   {60, 30, 0}. That run capped the axis at 60 on a page whose treating
   pressure reaches 78, and Treating Pressure came back with 17.2% of its
   samples, 1.43..60.32, the rest clipped off a scale that was never its own.

   A tick pair now also claims every label that lands on ITS line, judged in
   position, within one point. The same page's rate ladder read 20, 15, "1"
   (for 10) and "-5" (for 5), which has no arithmetic run in it at all, so
   axis B was not found — and that is where rule 2 took over.

2. A COLUMN IS ONE AXIS. p181 ("7.2  Interval 7") prints its letters at
   cx 94.1 (A), 655.6 (B) and 695.5 (C). Before rule 1 only C's ladder was
   found, at x 692.2, and `placed.setdefault(letter, near)` handed it to
   whichever letter reached it first in span order: B matched it at 36.7pt
   and took it, C — 3.3pt away, directly above it — got nothing, and A fell
   through to the positional fallback onto the same column. Both pressures
   were then read against 0..1500 kg/m3 and thrown out by the plausibility
   check, which is why the page reported two channels and not five. The
   nearest letter now claims a column and no other letter can.

3. THE PLOT FRAME IS RULED, SO READ IT. The export window's floor was the
   MEDIAN of the mapped columns' own tick extents, which is the frame only
   when the labels run to it. On an OCR'd sheet they never do: p181's three
   ladders are read to 370.6 (A's "30"), 387.2 (B's "5") and 426.1 (C's
   "200") down a frame that runs 138.5..470.7. The median put the floor at
   387.2 — the 25.0 MPa line — and Backside Pressure (a flat 18.6), Slurry
   Proppant Conc and BH Proppant Conc lie entirely below it, so all three
   lost every segment they had and were dropped, while Treating Pressure and
   Slurry Rate were sheared off at their floors. The page draws thirteen
   full-height vertical gridlines, every one of them 138.47..470.74, and
   their median is the frame whether or not one tick label was read.

   This is also why the defect could hide: finding MORE tick columns TIGHTENS
   a median, so every past improvement to column detection paid for the
   ladders it recovered with channels clipped away somewhere else.

4. AN AXIS IS TOLD FROM AN EVENT-MARKER LADDER BY WHERE IT REACHES ZERO — as
   a POSITION, not as a span down from its top tick. A span also carries
   where OCR stopped reading, which is evidence about nothing: on 00218 p328
   the rate ladder is read at 15, 10 and 5 and the concentration ladder at
   all fourteen of its labels, so their spans are 191.4 against 305.9, the
   ratio test threw the rate ladder away, and the page was left with one
   column that "B" then claimed from 34pt off — all five channels refused.
   The two ladders reach zero at 470.61 and 470.39, a fifth of a point
   apart, on a frame whose bottom rule the page draws at 470.28.

What the two pages come out as, measured, against what they print:

  p323 before  Tr Press     17.2%    1.43..60.32   on a 0..60 axis
               Backside    100.0%    9.47..19.68   on a 0..60 axis
       after   Tr Press    100.0%    1.43..77.95   on 0..100
               Backside    100.0%    9.47..19.68   on 0..100, unmoved
               Slurry Rate 100.0%   -0.03..12.65   on 0..20
               WH Conc     100.0%   -0.72..513.47  on 0..1500
               BH Conc     100.0%   -0.72..508.12  on 0..1500

  p181 before  WH Conc      46.0%  186.22..305.15  on 0..1500
               BH Conc      45.1%  186.22..301.51  on 0..1500
       after   Tr Press    100.0%    1.42..76.20   on 0..100
               Backside    100.0%   14.81..18.64   on 0..100
               Slurry Rate 100.0%   -0.03..11.60   on 0..20
               WH Conc     100.0%   -1.35..306.80  on 0..1500
               BH Conc     100.0%   -1.35..302.91  on 0..1500

Every one of those "after" numbers is what the sheet prints: p323's red curve
peaks a shade under 78 on the 0..100 ladder and its teal rate just over 12 on
the 0..20; p181's proppant pair tops out on the 300 gridline of the 0..1500,
and all five channels there start on the floor. The small negatives are the
window's own 2pt of slack at a floor the curves rest on — 0.1% of full scale
on the concentration ladder.

And what the line rule must NOT do, which is three pages, all of them
pages the reader already got right:

  - 00971 p135's section number "4.3" sits 123pt above the frame, in the
    ladder's own 14pt cluster, and 0.7 to 2.4pt off the lines a pair drawn
    through IT and a real label 250pt away will fit. So the window is ONE
    POINT and does not widen with the pair's reach: at 3pt those runs reach
    six labels against the ladder's own seven, close enough to win the
    visible-box tie-break, and the page read its 0..3.0 chemical ladder as
    0.01..4.31.
  - 00002 p339 draws its whole chart twice (visible_plot_box, #336), the
    pressure ladder at 33.4pt per 10 MPa and again, painted over, at 26.0.
    The hidden copy's "90" lands 7.4pt off the visible line, and the same
    one-point window is what keeps it out. Taken, it tilted the fit to
    0.14..99.60 against a printed 0..100 and read Treating Pressure as
    77.52 where the page prints 77.9.
  - 00002 p414 draws its two copies at the SAME scale — the two ladders are
    0.05 to 0.35pt apart, so no window keeps them apart. A value appears
    once on an axis, so the line keeps the nearer of two labels reading the
    same number. Without that the pressure column came back with 21 ticks
    instead of 11, ten of them a second reading of a point already on the
    line, and the doubled weight tilted the fit to 0.06..100.02.

All three come back to what they read before any of this.
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


# 00217 p323's own plot frame, and the black numerics its OCR returns in the
# two clusters the ladders fall into. "35.2" is the section number at the top
# of the sheet; it is 10.8pt from the ladder in x, which is inside the 14pt
# window an OCR'd page clusters on.
BOX = fitz.Rect(111.96, 138.36, 640.68, 470.28)
PRESSURE = [sp("35.2", 83.70, 80.10), sp("100", 94.50, 137.88),
            sp("60", 101.34, 270.90), sp("30", 101.34, 370.62),
            sp("0", 101.52, 470.34)]
RATE = [sp("20", 655.20, 137.88), sp("15", 651.96, 221.04),
        sp("1", 647.28, 304.20), sp("-5", 648.18, 387.18)]


class AnAxisIsALine(unittest.TestCase):

    def col(self, spans, box=BOX):
        cols = ifs._axis_columns(list(spans), box)
        self.assertEqual(len(cols), 1, [c["x"] for c in cols])
        return cols[0]

    def at(self, c, y):
        return c["a"] + c["b"] * y

    def test_the_pressure_ladder_reaches_100_not_60(self):
        # the FIT was never in doubt — {60, 30, 0} sits on the same line as
        # the 100 above it, and extrapolates to 100 at 137.88 either way.
        # What the arithmetic run got wrong is how far the axis REACHES, and
        # that is the number the export window and meta.axes are cut to.
        c = self.col(PRESSURE)
        self.assertAlmostEqual(self.at(c, c["y_hi"]), 0.0, delta=0.2)
        self.assertAlmostEqual(self.at(c, c["y_lo"]), 100.0, delta=0.2)

    def test_the_section_number_is_not_a_tick(self):
        c = self.col(PRESSURE)
        self.assertEqual(c["n"], 4)                  # 100, 60, 30, 0
        # and it would have to sit 273pt lower than it does to be one
        self.assertGreater(abs(self.at(c, 80.10) - 35.2), 70.0)

    def test_the_arithmetic_run_alone_capped_it_at_60(self):
        # with the 100 label taken away, 60 IS the top of what the page
        # showed: the line rule adds nothing it cannot see
        c = self.col([s for s in PRESSURE if s["t"] != "100"])
        self.assertEqual(c["n"], 3)
        self.assertAlmostEqual(self.at(c, c["y_lo"]), 60.0, delta=0.2)

    def test_the_rate_ladder_has_no_arithmetic_run_and_is_still_read(self):
        c = self.col(RATE)
        self.assertAlmostEqual(self.at(c, c["y_lo"]), 20.0, delta=0.2)
        self.assertAlmostEqual(self.at(c, c["y_hi"]), 5.0, delta=0.2)
        # 0 was never printed low enough for OCR to catch, but the line the
        # three read labels fit runs to it at the frame's own floor
        self.assertAlmostEqual(self.at(c, 470.34), 0.0, delta=0.2)

    def test_the_mis_read_10_is_refused(self):
        # OCR returned "1" for the 10 label; on this ladder a 1 belongs
        # 150pt below where that label sits
        self.assertEqual(self.col(RATE)["n"], 3)     # 20, 15, 5

    def test_a_pair_and_a_stray_is_not_a_ladder(self):
        # three points are still required: two ticks plus a label that is
        # nowhere near their line makes no column at all
        self.assertEqual(
            ifs._axis_columns([sp("20", 655.20, 137.88),
                               sp("15", 651.96, 221.04),
                               sp("1", 647.28, 304.20)], BOX), [])

    def test_a_text_page_still_needs_four(self):
        # the same labels without the ocr flag: a text page's ladder is
        # complete, so a three-point line there is a coincidence
        text = [text_sp(s["t"], s["cx"], s["cy"])
                for s in PRESSURE if s["t"] != "35.2"]
        self.assertEqual(ifs._axis_columns(text[:3], BOX), [])


# 00971 p135, "4.3 Interval 4 - Chemical Additives": a 0..3.0 ladder every
# 0.5, read whole, with the section number 123pt above the frame in the same
# 14pt cluster. A pair drawn through "4.3" and a real label fits several of
# the others to within 2.4pt.
P135_BOX = fitz.Rect(86.76, 72.12, 507.24, 720.0)
P135 = [sp("4.3", -711.36, 80.10), sp("3.0", -699.66, 202.68),
        sp("2.5", -699.48, 247.32), sp("2.0", -699.66, 291.78),
        sp("1.5", -698.94, 336.24), sp("1.0", -699.12, 380.88),
        sp("0.5", -699.48, 425.34), sp("0.0", -699.66, 469.98)]

# 00002 p339's pressure ladder, both copies, as the page's own text layer
# gives them: the visible one steps 33.4pt per 10 MPa, the one painted over
# it 26.0. They share the "100" at the top, which is why the hidden copy's
# "90" is the one that can reach the visible line.
P339_BOX = fitz.Rect(110.40, 135.19, 642.79, 468.45)
VIS = [("100", 93.55, 135.13), ("90", 96.98, 168.53), ("80", 96.98, 201.93),
       ("70", 96.98, 235.34), ("60", 96.98, 268.68), ("50", 96.98, 302.09),
       ("40", 96.98, 335.49), ("30", 96.98, 368.89), ("20", 96.98, 402.29),
       ("10", 96.98, 435.70), ("0", 100.40, 469.05)]
HID = [("100", 93.55, 135.13), ("90", 96.98, 161.14), ("80", 96.98, 187.11),
       ("70", 96.98, 213.12), ("60", 96.98, 239.08), ("50", 96.98, 265.10),
       ("40", 96.98, 291.06), ("30", 96.98, 317.08), ("20", 96.98, 343.04),
       ("10", 96.98, 369.06), ("0", 100.40, 395.02)]


class WhatTheLineMayNotClaim(unittest.TestCase):
    """The one-point window, on the two pages that need it."""

    def test_00971_p135_keeps_its_own_seven_labels(self):
        cols = ifs._axis_columns(list(P135), P135_BOX)
        self.assertEqual(len(cols), 1)
        c = cols[0]
        self.assertEqual(c["n"], 7)          # 3.0 down to 0.0, not "4.3"
        self.assertAlmostEqual(c["a"] + c["b"] * 202.68, 3.0, delta=0.02)
        self.assertAlmostEqual(c["a"] + c["b"] * 469.98, 0.0, delta=0.02)

    def test_00002_p339_reads_the_visible_ladder(self):
        spans = [text_sp(*t) for t in VIS + HID]
        cols = ifs._axis_columns(spans, P339_BOX)
        self.assertEqual(len(cols), 1)
        c = cols[0]
        self.assertEqual(c["n"], 11)          # eleven labels, not thirteen
        self.assertAlmostEqual(c["a"] + c["b"] * 469.05, 0.0, delta=0.05)
        self.assertAlmostEqual(c["a"] + c["b"] * 135.13, 100.0, delta=0.05)

    def test_00002_p339_the_hidden_ladder_alone_still_reads_0_to_100(self):
        # the rule is about which copy, not about refusing one of them
        c = ifs._axis_columns([text_sp(*t) for t in HID], None)[0]
        self.assertAlmostEqual(c["a"] + c["b"] * 395.02, 0.0, delta=0.05)


# 00002 p414, the same doubled page at ONE scale: every label is printed
# twice, 0.05 to 0.35pt apart, which no position window can separate.
P414_BOX = fitz.Rect(110.40, 135.19, 642.79, 394.42)
P414 = [("100", 93.55, 135.18), ("100", 93.55, 135.13),
        ("90", 96.98, 161.14), ("90", 96.98, 161.23),
        ("80", 96.98, 187.11), ("80", 96.98, 187.22),
        ("70", 96.98, 213.12), ("70", 96.98, 213.27),
        ("60", 96.98, 239.08), ("60", 96.98, 239.26),
        ("50", 96.98, 265.10), ("50", 96.98, 265.30),
        ("40", 96.98, 291.06), ("40", 96.98, 291.29),
        ("30", 96.98, 317.08), ("30", 96.98, 317.34),
        ("20", 96.98, 343.04), ("20", 96.98, 343.33),
        ("10", 96.98, 369.06), ("10", 96.98, 369.37),
        ("0", 100.40, 395.02), ("0", 100.40, 395.37)]


class OneValueIsOnePlace(unittest.TestCase):
    """00002 p414: a label read twice is one tick, not two."""

    def test_the_ladder_has_eleven_ticks_not_twenty_one(self):
        c = ifs._axis_columns([text_sp(*t) for t in P414], P414_BOX)[0]
        self.assertEqual(c["n"], 11)

    def test_and_the_fit_is_the_printed_0_to_100(self):
        c = ifs._axis_columns([text_sp(*t) for t in P414], P414_BOX)[0]
        self.assertAlmostEqual(c["a"] + c["b"] * 395.02, 0.0, delta=0.02)
        self.assertAlmostEqual(c["a"] + c["b"] * 135.18, 100.0, delta=0.02)


# 00218 p328 ("35.2 Interval 35"). OCR read three labels of the rate ladder
# and all fourteen of the concentration ladder; the pressure ladder returned
# two, which is below the three a column needs, so it is not here.
P328_BOX = fitz.Rect(111.96, 164.88, 640.68, 470.28)
P328_RATE = [sp("15", 655.92, 279.18), sp("-10", 651.78, 342.90),
             sp("-5", 648.18, 406.80)]
P328_CONC = [sp("1500", 695.88, 164.52), sp("+1400", 691.92, 185.04),
             sp("+1300", 691.92, 205.20), sp("+1200", 691.92, 225.72),
             sp("+1000", 691.92, 266.40), sp("+900", 688.14, 286.92),
             sp("+800", 688.14, 307.26), sp("+700", 688.14, 327.60),
             sp("+600", 688.14, 348.12), sp("+500", 688.14, 368.28),
             sp("+400", 688.14, 388.80), sp("+300", 688.14, 409.32),
             sp("+200", 688.14, 429.48), sp("+100", 688.14, 450.00)]


class AnAxisIsKnownByItsZero(unittest.TestCase):
    """00218 p328: a short ladder beside a long one is still a ladder."""

    def cols(self):
        return ifs._axis_columns(list(P328_RATE + P328_CONC), P328_BOX)

    def test_both_ladders_survive(self):
        got = self.cols()
        self.assertEqual(len(got), 2, [(c["x"], c["n"]) for c in got])

    def test_the_concentration_ladder_reaches_1500(self):
        conc = max(self.cols(), key=lambda c: c["n"])
        self.assertEqual(conc["n"], 14)
        self.assertAlmostEqual(conc["a"] + conc["b"] * 164.52, 1500.0,
                               delta=2.0)

    def test_the_rate_ladder_is_read_5_to_15(self):
        rate = min(self.cols(), key=lambda c: c["n"])
        self.assertEqual(rate["n"], 3)
        self.assertAlmostEqual(rate["a"] + rate["b"] * 279.18, 15.0,
                               delta=0.05)

    def test_they_agree_on_where_zero_is(self):
        # which is the whole of the argument for keeping both: 470.61 and
        # 470.39, against a frame the page rules at 470.28
        zeros = [-c["a"] / c["b"] for c in self.cols()]
        self.assertAlmostEqual(min(zeros), max(zeros), delta=1.0)
        for z in zeros:
            self.assertAlmostEqual(z, 470.28, delta=1.0)


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/"
                  "00217-105130506505W602_0496117_COMP.pdf")

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
class OnTheReportedPage(unittest.TestCase):
    """00217 p323, the page Carmine filed the issue against."""

    def setUp(self):
        self.doc = fitz.open(DRIVE[0])

    def tearDown(self):
        self.doc.close()

    def test_treating_pressure_is_read_on_the_0_to_100_ladder(self):
        got, meta = _read(self.doc[322])
        pct, lo, hi = got["Tr Press"]
        self.assertEqual(pct, 100.0)                 # was 17.2
        self.assertAlmostEqual(hi, 77.95, delta=0.5)  # printed just under 78
        self.assertAlmostEqual(meta.axes["Tr Press"][1], 100.0, delta=0.5)

    def test_the_three_channels_that_had_no_axis_are_there(self):
        got, meta = _read(self.doc[322])
        self.assertEqual(sorted(got), ALL_FIVE)
        self.assertAlmostEqual(got["Slurry Rate"][2], 12.65, delta=0.3)
        self.assertAlmostEqual(got["WH Prop Conc"][2], 513.47, delta=6.0)
        self.assertAlmostEqual(meta.axes["Slurry Rate"][1], 20.0, delta=0.3)
        self.assertAlmostEqual(meta.axes["WH Prop Conc"][1], 1500.0,
                               delta=5.0)

    def test_backside_pressure_did_not_move(self):
        # it was already on the right LINE — the 0..60 axis and the 0..100
        # axis are the same fit, one of them just stopped short
        got, _meta = _read(self.doc[322])
        self.assertEqual(got["Backside Pressure"][0], 100.0)
        self.assertAlmostEqual(got["Backside Pressure"][1], 9.47, delta=0.2)
        self.assertAlmostEqual(got["Backside Pressure"][2], 19.68, delta=0.2)


@unittest.skipUnless(DRIVE and ocr_labels.available(),
                     "the AER drive or tesseract is not here")
class OnTheOneColumnPage(unittest.TestCase):
    """00217 p181, where one ladder was read and three letters claimed it."""

    def setUp(self):
        self.doc = fitz.open(DRIVE[0])

    def tearDown(self):
        self.doc.close()

    def test_every_channel_lands_on_its_own_printed_ladder(self):
        got, meta = _read(self.doc[180])
        self.assertEqual(sorted(got), ALL_FIVE)
        self.assertAlmostEqual(meta.axes["Tr Press"][1], 100.0, delta=0.5)
        self.assertAlmostEqual(meta.axes["Slurry Rate"][1], 20.0, delta=0.3)
        self.assertAlmostEqual(meta.axes["BH Prop Conc"][1], 1500.0,
                               delta=5.0)

    def test_the_proppant_pair_keeps_the_peak_it_already_had(self):
        # before, both concentrations WERE on the concentration ladder and
        # their peaks were right; it was the bottom of the chart that was
        # missing, 45% of the samples and a floor of 186 kg/m3 on a channel
        # the page draws resting on zero until 22:18
        got, _meta = _read(self.doc[180])
        for k, peak in (("WH Prop Conc", 306.80), ("BH Prop Conc", 302.91)):
            pct, lo, hi = got[k]
            self.assertEqual(pct, 100.0)             # was 46.0 / 45.1
            self.assertAlmostEqual(hi, peak, delta=5.0)
            self.assertLess(abs(lo), 8.0)            # was 186.22

    def test_the_pressures_come_back(self):
        got, _meta = _read(self.doc[180])
        self.assertAlmostEqual(got["Tr Press"][2], 76.20, delta=0.5)
        self.assertAlmostEqual(got["Backside Pressure"][2], 18.64, delta=0.3)
        self.assertAlmostEqual(got["Slurry Rate"][2], 11.60, delta=0.3)


@unittest.skipUnless(DRIVE and ocr_labels.available(),
                     "the AER drive or tesseract is not here")
class TheWindowIsTheRuledFrame(unittest.TestCase):
    """The export window comes off the gridlines, not the tick labels."""

    def test_the_frame_is_the_page_s_own_138_to_470(self):
        doc = fitz.open(DRIVE[0])
        for pno in (180, 322):
            meta, _s, _d, _i = ifs.extract_page(doc[pno])
            self.assertAlmostEqual(meta.geom["v0"], 138.47, delta=0.5)
            self.assertAlmostEqual(meta.geom["v1"], 470.74, delta=0.5)
        doc.close()


if __name__ == "__main__":
    unittest.main()
