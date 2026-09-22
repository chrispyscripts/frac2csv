"""An axis date the calendar refuses is not a date.

  python3 -m unittest tests.test_ifs_axis_date

_axis_date reads the date printed under the clock row. It accepts two
printed forms, and until now it checked only one of them: the M/D form goes
through _mdy, which refuses a month outside 1-12 and a day outside 1-31,
while the ISO form was reassembled from the regex groups and returned
unexamined.

On 00971 (Crew Monias B3-13, BCER Spud-2019-2023) that difference reaches
the CSV. Every string in the filing is drawn as outlines, so every label is
OCR'd, and two of its pages lose a digit in the month field:

    p134   reads "2051-00-02"     exports 2051-00-02
    p157   reads "2021-00-03"     exports 2021-00-03

Month zero. Both pages extract cleanly otherwise — the chart is read, the
channels are right, and the DATETIME column carries a date no calendar
accepts. _start_stamp would also raise outright on either one the moment a
chart crossed midnight, because it parses label_date with strptime.

So the ISO form is now held to the same range test the M/D form has always
been held to, and a label that fails it is refused rather than exported: the
page falls back to whatever else it prints, exactly as a mangled M/D label
already did.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import halliburton_ifs as ifs                            # noqa: E402


def sp(t, cx, cy):
    """An OCR'd span, as _spans hands one to the axis reader."""
    return {"t": t, "cx": cx, "cy": cy, "x0": 0.0, "x1": 0.0,
            "color": 0, "ocr": True}


# The clock row both files print under their plots, and the date line 7pt
# beneath it that _axis_date is looking for.
ROW = [sp("06:20", -502.0, 482.0), sp("06:40", -371.3, 482.0)]


def iso(text):
    return ifs._D_ISO.fullmatch(text)


class TheIsoFormIsChecked(unittest.TestCase):
    """_iso applies _mdy's range test to the other printed form."""

    def test_a_real_date_is_returned_unchanged(self):
        self.assertEqual(ifs._iso(iso("2021-09-01")), "2021-09-01")

    def test_month_zero_is_refused(self):
        # 00971 p157, as OCR reads it
        self.assertEqual(ifs._iso(iso("2021-00-03")), "")

    def test_month_zero_is_refused_whatever_the_year(self):
        # 00971 p134, where the year is mangled too. The year is NOT range
        # checked here and deliberately so: _mdy does not check one either,
        # and a wrong year is a different repair from a wrong month.
        self.assertEqual(ifs._iso(iso("2051-00-02")), "")

    def test_month_thirteen_is_refused(self):
        self.assertEqual(ifs._iso(iso("2021-13-02")), "")

    def test_day_zero_is_refused(self):
        self.assertEqual(ifs._iso(iso("2021-09-00")), "")

    def test_day_thirty_two_is_refused(self):
        self.assertEqual(ifs._iso(iso("2021-09-32")), "")

    def test_the_boundaries_themselves_are_kept(self):
        # the same bounds _mdy keeps, named so a tightening cannot be silent
        self.assertEqual(ifs._iso(iso("2021-01-01")), "2021-01-01")
        self.assertEqual(ifs._iso(iso("2021-12-31")), "2021-12-31")


class WhatAxisDateDoesWithOne(unittest.TestCase):
    """A refused label is not exported, and does not hide a good one."""

    def test_a_good_iso_label_is_read(self):
        got = ifs._axis_date(ROW + [sp("2021-09-01", -241.0, 489.0)], ROW)
        self.assertEqual(got, "2021-09-01")

    def test_month_zero_does_not_reach_the_caller(self):
        got = ifs._axis_date(ROW + [sp("2021-00-03", -241.0, 489.0)], ROW)
        self.assertNotEqual(got, "2021-00-03")
        self.assertEqual(got, "")

    def test_a_refused_iso_label_lets_a_printed_mdy_date_stand(self):
        # both printed under the row: the ISO one is mangled, the other is
        # not, and the page should be read rather than given up on
        spans = ROW + [sp("2021-00-03", -241.0, 489.0),
                       sp("9/1/2021", -502.0, 489.0)]
        self.assertEqual(ifs._axis_date(spans, ROW), "2021-09-01")

    def test_a_refused_iso_label_still_reaches_the_fallback_scan(self):
        # the M/D date is NOT under the axis row, so only the second pass
        # over the whole page can find it
        spans = ROW + [sp("2021-00-03", -241.0, 489.0),
                       sp("9/1/2021", -600.0, 60.0)]
        self.assertEqual(ifs._axis_date(spans, ROW), "2021-09-01")

    def test_the_leftmost_good_label_still_wins(self):
        # unchanged behaviour: _axis_date takes the smallest cx
        spans = ROW + [sp("2021-09-02", -241.0, 489.0),
                       sp("2021-09-01", -632.0, 489.0)]
        self.assertEqual(ifs._axis_date(spans, ROW), "2021-09-01")


class WhatTheCsvWouldHaveCarried(unittest.TestCase):
    """The consequence, stated as a test so it cannot come back quietly."""

    def test_every_exported_axis_date_parses_as_a_date(self):
        from datetime import datetime
        for text in ("2021-09-01", "2021-00-03", "2051-00-02",
                     "2021-13-02", "2021-09-00", "2021-09-32"):
            got = ifs._axis_date(ROW + [sp(text, -241.0, 489.0)], ROW)
            if got:
                datetime.strptime(got, "%Y-%m-%d")   # raises if it is not one

    def test_start_stamp_can_parse_what_axis_date_returns(self):
        # _start_stamp calls strptime on this string the moment a chart
        # crosses midnight, so an unparseable date is a crash in waiting
        got = ifs._axis_date(ROW + [sp("2021-00-03", -241.0, 489.0)], ROW)
        self.assertEqual(got, "")
        date, clock = ifs._start_stamp("2021-09-01", 86400 + 3600)
        self.assertEqual(date, "2021-09-02")
        self.assertEqual(clock, "01:00:00")


if __name__ == "__main__":
    unittest.main()
