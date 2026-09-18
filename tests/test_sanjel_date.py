"""A date the page prints is not automatically a date.

Sanjel's generator writes an empty date cell the way Excel does: serial 0,
which prints as "January 0, 1900". 00104 p37 prints exactly that, and the
reader transcribed it into 1900-01-00 — a day that is not on the calendar.
datetime will not parse it, and the handover placed that stage a century from
the rest of the well, cutting its neighbours by the largest amounts on the
page (8.7, 10.0, 7.0 min).

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sanjel                                            # noqa: E402


class RealDate(unittest.TestCase):
    def test_excel_zero_day_is_not_a_date(self):
        # the exact value 00104 p37 prints
        self.assertEqual(sanjel._real_date(1900, 1, 0), "")

    def test_ordinary_dates_are_unchanged(self):
        self.assertEqual(sanjel._real_date(2016, 2, 2), "2016-02-02")

    def test_a_leap_day_is_a_day(self):
        self.assertEqual(sanjel._real_date(2016, 2, 29), "2016-02-29")

    def test_the_day_after_a_leap_day_that_is_not(self):
        self.assertEqual(sanjel._real_date(2015, 2, 29), "")

    def test_impossible_months_and_days(self):
        for y, mo, d in ((2016, 13, 1), (2016, 0, 5), (2016, 2, 30), (2016, 4, 31)):
            self.assertEqual(sanjel._real_date(y, mo, d), "", f"{y}-{mo}-{d}")

    def test_strings_are_accepted_the_way_the_regexes_hand_them_over(self):
        self.assertEqual(sanjel._real_date("2016", "02", "02"), "2016-02-02")
        self.assertEqual(sanjel._real_date("1900", "01", "00"), "")

    def test_every_returned_date_parses(self):
        from datetime import date
        for args in ((2016, 2, 2), (2016, 2, 29), (1999, 12, 31)):
            got = sanjel._real_date(*args)
            date.fromisoformat(got)          # raises if it does not


if __name__ == "__main__":
    unittest.main()
