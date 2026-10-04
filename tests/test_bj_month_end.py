"""A BJ-1 chart over the end of a month that is not 31 days long.

  python3 -m unittest tests.test_bj_month_end

bj1 clocked each "Mon-DD HH:MM" label as (month*31 + day) days, so the step
from "Nov-30 23:45" to "Dec-01 00:00" was two days and fifteen minutes. The
time fit bent through it: 01793 stage 11 (Nov-30 22:40 .. Dec-01 00:00) read as
starting 19:34 and lasting 837 minutes, an 80-minute chart. A chart over
Apr-30, or over Feb-28 in a common year, failed outright on "implausible
duration". The pages are the same synthetic BJ-1 chart test_bj_start_date
builds: eight labels 15 minutes apart, curves drawn from a known instant.
"""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import bj1                                               # noqa: E402
import test_bj_start_date as built                       # noqa: E402


def _read(first, start_min):
    return built._read(first, start_min, year_hint=first.year)


class AcrossAMonthEnd(unittest.TestCase):

    def assertReads(self, first, start_min=5):
        meta = _read(first, start_min)
        drawn = first + datetime.timedelta(minutes=start_min)
        self.assertAlmostEqual((built._instant(meta) - drawn).total_seconds(), 0,
                               delta=20)
        # the same chart wholly inside one month, for its length
        same = _read(datetime.datetime(2025, 5, 5, first.hour, first.minute),
                     start_min)
        self.assertAlmostEqual(meta.duration_min, same.duration_min, delta=0.2)
        return meta

    def test_a_30_day_month(self):
        self.assertReads(datetime.datetime(2025, 11, 30, 23, 0))   # 01793's
        self.assertReads(datetime.datetime(2025, 4, 30, 23, 0))

    def test_february_in_a_common_year(self):
        self.assertReads(datetime.datetime(2025, 2, 28, 23, 0))

    def test_february_in_a_leap_year(self):
        self.assertReads(datetime.datetime(2024, 2, 28, 23, 0))    # into Feb-29
        self.assertReads(datetime.datetime(2024, 2, 29, 23, 0))    # out of it

    def test_a_31_day_month_and_the_new_year_still_read(self):
        self.assertReads(datetime.datetime(2025, 7, 31, 23, 0))
        self.assertReads(datetime.datetime(2025, 12, 31, 23, 30), 2)

    def test_a_start_before_the_first_of_a_month(self):
        meta = self.assertReads(datetime.datetime(2025, 11, 1, 0, 0), -2)
        self.assertEqual(meta.date, "2025-10-31")


class CalendarClock(unittest.TestCase):
    """The correction itself, on bare label tuples."""

    @staticmethod
    def _labels(stamps, x0=100.0, step=55.2):
        tpts, daytags, tlabels = [], [], []
        for k, (mo, d, hh, mm) in enumerate(stamps):
            s = (mo * 31 + d) * 86400 + hh * 3600 + mm * 60
            tpts.append((s, x0 + k * step, 600.0))
            daytags.append((s, mo, d))
            tlabels.append((s, f"{mo}-{d} {hh}:{mm}"))
        return tpts, daytags, tlabels

    def test_one_month_comes_back_untouched(self):
        args = self._labels([(5, 5, 23, 0), (5, 5, 23, 15), (5, 5, 23, 30)])
        out = bj1._calendar_clock(*args)
        self.assertEqual(out, args)

    def test_a_30_day_month_end_steps_fifteen_minutes(self):
        tp, _d, _l = bj1._calendar_clock(*self._labels(
            [(11, 30, 23, 30), (11, 30, 23, 45), (12, 1, 0, 0), (12, 1, 0, 15)]))
        steps = [b[0] - a[0] for a, b in zip(tp, tp[1:])]
        self.assertEqual(steps, [900, 900, 900])

    def test_february_length_is_read_off_the_labels(self):
        tp, _d, _l = bj1._calendar_clock(*self._labels(
            [(2, 28, 23, 30), (2, 28, 23, 45), (3, 1, 0, 0), (3, 1, 0, 15)]))
        self.assertEqual([b[0] - a[0] for a, b in zip(tp, tp[1:])], [900] * 3)

    def test_no_labels_no_change(self):
        self.assertEqual(bj1._calendar_clock([], [], []), ([], [], []))


if __name__ == "__main__":
    unittest.main()
