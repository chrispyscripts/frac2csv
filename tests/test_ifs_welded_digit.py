"""A tick mark welded onto the END of an OCR'd IFS label, as a DIGIT.

00149 p139's pressure ladder is printed 100, 90, 80, 70, 60, 50, 40, 30, 20,
10 — perfectly legibly. The page is filed rotated, so its labels are read by
OCR, and the tick stub above each numeral is absorbed into the word box and
comes back as a trailing 5:

    read:     100   805   705    60   505    40    30   205   105
    printed:  100    80    70    60    50    40    30    20    10

The strip already in _axis_columns removes a leading or trailing NON-numeric
speck, so these stay numeric and are believed. And they are self-consistent:
805, 705, 505, 205, 105 sit on their own straight line — five members against
the four clean ones — so the consensus fit PREFERS them and the column comes
back 105..805 instead of 10..100.

Both pressure channels are then deleted by the plausibility guard, correctly,
as an axis that cannot belong to them. The chart ships three curves instead
of five and looks like missing data rather than a misread axis. That is
Carmine's "no Tr Press" and "missed a lot of stages" (2026-09-24), on every
treatment chart of the file but three.

The repair offers each label a second reading — itself with the last digit
gone — and keeps it only where that puts strictly MORE of the column on one
straight line. A ladder that reads correctly already explains all of itself,
so it cannot be touched.

  python3 -m unittest tests.test_ifs_welded_digit
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import halliburton_ifs as ifs                              # noqa: E402


def _col(pairs, cx=-692.5):
    """[(text, cy)] -> the span dicts _unweld_tick_digit expects."""
    return [{"t": t, "cx": cx, "cy": cy, "color": 0, "ocr": True}
            for t, cy in pairs]


class Unweld(unittest.TestCase):

    # 00149 p139, verbatim: the values OCR returned and where it put them
    P139 = [("100", 139.5), ("805", 205.4), ("705", 238.3), ("60", 271.3),
            ("505", 304.2), ("40", 337.1), ("30", 370.1), ("205", 403.2),
            ("105", 436.1)]

    def test_the_welded_digit_comes_off(self):
        spans = _col(self.P139)
        ifs._unweld_tick_digit(spans)
        got = [s["t"] for s in spans]
        self.assertEqual(got, ["100", "80", "70", "60", "50", "40", "30",
                               "20", "10"])

    def test_the_repair_has_to_explain_more_than_believing_the_page(self):
        # the five corrupted labels alone DO form a line — that is why the
        # column preferred them — so the rule cannot be "a line exists"
        spans = _col([("805", 205.4), ("705", 238.3), ("505", 304.2),
                      ("205", 403.2), ("105", 436.1)])
        ifs._unweld_tick_digit(spans)
        self.assertEqual([s["t"] for s in spans],
                         ["805", "705", "505", "205", "105"],
                         "a column that is self-consistent as read is left alone")

    def test_a_clean_ladder_is_never_rewritten(self):
        for ladder in ([("100", 139.5), ("80", 205.4), ("70", 238.3),
                        ("60", 271.3), ("50", 304.2), ("40", 337.1)],
                       [("1000", 100.0), ("800", 200.0), ("600", 300.0),
                        ("400", 400.0), ("200", 500.0)],
                       [("20", 164.5), ("15", 241.0), ("10", 317.5),
                        ("5", 394.0), ("0", 470.5)]):
            spans = _col(ladder)
            before = [s["t"] for s in spans]
            ifs._unweld_tick_digit(spans)
            self.assertEqual([s["t"] for s in spans], before, str(ladder[:2]))

    def test_a_short_column_is_left_alone(self):
        # three labels cannot vouch for a repair of themselves
        spans = _col([("805", 205.4), ("705", 238.3), ("60", 271.3)])
        ifs._unweld_tick_digit(spans)
        self.assertEqual([s["t"] for s in spans], ["805", "705", "60"])

    def test_columns_are_judged_apart(self):
        # two ladders on one page must not pool their readings
        spans = _col(self.P139, cx=-692.5) + _col(
            [("1000", 139.5), ("800", 205.4), ("600", 271.3),
             ("400", 337.1), ("200", 403.2)], cx=-101.5)
        ifs._unweld_tick_digit(spans)
        self.assertEqual([s["t"] for s in spans][-5:],
                         ["1000", "800", "600", "400", "200"])


BC = "/Volumes/CnC-2TB-ssd/AER-Frac-Montney-ARC/"
P149 = glob.glob(BC + "00149-102051106404W600_0493962_COMP.pdf")


@unittest.skipUnless(P149, "the AER drive is not mounted")
class OnThePage(unittest.TestCase):
    """00149 p139 — one of the charts Carmine reported."""

    def test_both_pressures_come_back(self):
        import fitz
        meta, samples, data, chinfo = ifs.extract_page(
            fitz.open(P149[0])[138])[:4]
        self.assertIn("Tr Press", data)
        self.assertIn("Backside Pressure", data)
        # against the ladder the page prints, not the concentration one it
        # was reading (105..805) before the repair
        lo, hi = meta.axes["Tr Press"]
        self.assertLessEqual(hi, 110.0)
        self.assertGreaterEqual(hi, 90.0)


if __name__ == "__main__":
    unittest.main()
