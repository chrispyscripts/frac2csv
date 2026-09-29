"""A rate ladder OCR cut down to two readable labels (#754).

00217 prints its rate axis 20/15/10/5/0 and OCR returns, on 31 of the file's
125 treatment charts:

    '20' @164.52   '15' @241.02   '4' @317.34   (nothing)   (nothing)

The 10 is misread, the 5 and the 0 are not returned at all. The longest
arithmetic chain is therefore {20, 15} -- two labels, below the three an OCR
page requires -- so the column is dropped, Slurry Rate has no scale, and it is
cut from the chart. Carmine: "this one is missing the the rate on most
charts".

Three is the right floor in general: two points always fit a line, so a pair
vouches for nothing by itself. What vouches for it here is the PAGE. Every
ladder on one of these plots runs the full height of the same frame, so they
all reach zero at the same y -- measured over 00217 and 00149, a page's own
columns agree on that position to a median 0.29pt. _axis_columns already
leans on this to throw out event-marker ladders (#77); the rescue asks the
same question of a pair.

The guards are the point, and each is measured:

  * 00149 keeps all three of its ladders on 32 charts. Without the
    "page is short" guard the rescue would add a FOURTH column on two of
    them.
  * the '4' is not junk to be ignored -- it makes two more pairs, (20, 4) and
    (15, 4). Both are refused because they put zero 115 and 125pt above the
    frame's bottom rule, and if either had qualified the column would be
    ambiguous and left alone.

  python3 -m unittest tests.test_ifs_two_label_ladder
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import halliburton_ifs as ifs                                 # noqa: E402


# 00217 p226, verbatim: the frame's bottom rule is at y=470.28 and both
# surviving ladders reach zero on it.
FRAME_TOP, FRAME_BOT = 164.88, 470.28


def _col(v_top, v_bot, n, x, y_lo=FRAME_TOP, y_hi=FRAME_BOT):
    b = (v_top - v_bot) / (y_lo - y_hi)
    a = v_top - b * y_lo
    return {"x": x, "a": a, "b": b, "n": n, "y_lo": y_lo, "y_hi": y_hi}


def _spans(pairs, cx=655.0):
    return [{"t": t, "cx": cx, "cy": cy, "color": 0, "ocr": True}
            for t, cy in pairs]


PRESSURE = _col(100.0, 0.0, 8, 100.44)
CONC = _col(1500.0, 0.0, 7, 690.81)
RATE_AS_READ = _spans([("20", 164.52), ("15", 241.02), ("4", 317.34)])


class TheRescue(unittest.TestCase):

    def test_the_rate_ladder_comes_back(self):
        got = ifs._rescue_pair_columns([RATE_AS_READ], [PRESSURE, CONC])
        self.assertEqual(len(got), 1)
        c = got[0]
        self.assertAlmostEqual(c["a"] + c["b"] * FRAME_TOP, 20.0, delta=0.1)
        self.assertAlmostEqual(c["a"] + c["b"] * FRAME_BOT, 0.0, delta=0.1)

    def test_it_picks_the_pair_that_lands_on_the_page_s_zero(self):
        """(20,4) and (15,4) exist too; both miss by more than 100pt."""
        c = ifs._rescue_pair_columns([RATE_AS_READ], [PRESSURE, CONC])[0]
        self.assertAlmostEqual(-c["a"] / c["b"], 470.5, delta=1.0)

    def test_two_labels_are_enough_when_they_are_the_only_two(self):
        got = ifs._rescue_pair_columns(
            [_spans([("20", 164.52), ("15", 241.02)])], [PRESSURE, CONC])
        self.assertEqual(len(got), 1)


class WhatItRefuses(unittest.TestCase):

    def test_a_page_that_already_has_three_ladders(self):
        """00149 keeps all three on 32 charts; a fourth would be invented."""
        got = ifs._rescue_pair_columns(
            [RATE_AS_READ], [PRESSURE, CONC, _col(25.0, 0.0, 5, 400.0)])
        self.assertEqual(got, [])

    def test_a_pair_that_reaches_zero_somewhere_else(self):
        # 20 and 15 half as far apart: zero lands mid-plot, not on the rule
        got = ifs._rescue_pair_columns(
            [_spans([("20", 164.52), ("15", 202.77)])], [PRESSURE, CONC])
        self.assertEqual(got, [])

    def test_an_ambiguous_column_is_left_alone(self):
        """Two pairs both landing on the zero cannot both be the ladder."""
        # 20@164.52 and 15@241.02 land on it; add 10@317.52, which with 20
        # ALSO lands on it — three labels, two qualifying pairs
        got = ifs._rescue_pair_columns(
            [_spans([("20", 164.52), ("15", 241.02), ("10", 317.52)])],
            [PRESSURE, CONC])
        self.assertEqual(got, [], "an unambiguous 3-chain is not this "
                                  "function's job — _axis_columns takes it")

    def test_nothing_to_calibrate_against(self):
        self.assertEqual(ifs._rescue_pair_columns([RATE_AS_READ], [PRESSURE]),
                         [])


BC = "/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/"
P217 = glob.glob(BC + "00217-105130506505W602_0496117_COMP.pdf")
P149 = glob.glob(BC + "00149-102051106404W600_0493962_COMP.pdf")


@unittest.skipUnless(P217, "the AER drive is not mounted")
class OnThePage(unittest.TestCase):

    def test_00217_chart_16_has_its_rate(self):
        """The chart Carmine reported: page 226, stage 16."""
        import fitz
        meta, _samples, data = ifs.extract_page(fitz.open(P217[0])[225])[:3]
        self.assertIn("Slurry Rate", data)
        lo, hi = meta.axes_frame["Slurry Rate"]
        self.assertAlmostEqual(min(lo, hi), 0.0, delta=0.5)
        self.assertAlmostEqual(max(lo, hi), 20.0, delta=0.5)

    @unittest.skipUnless(P149, "the AER drive is not mounted")
    def test_00149_is_not_touched(self):
        """Its ladders are not zero-based, so the rescue must never fire."""
        import fitz
        meta, _samples, data = ifs.extract_page(fitz.open(P149[0])[138])[:3]
        self.assertIn("Tr Press", data)
        self.assertIn("Backside Pressure", data)


if __name__ == "__main__":
    unittest.main()
