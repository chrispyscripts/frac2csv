"""Canyon: when the printed interval summary dates a chart, and when it does not.

  python3 -m unittest tests.test_canyon_dates

00009 prints the job's start date on every chart page, so the summary is the
only place an interval's own day is written. 00237 prints the day each
interval ran, and its summary is the one that is wrong: it puts intervals 2-12
on 11-27, the same morning as 13-17, while their pages print 11-26.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                           # noqa: E402

COLS = ["Interval", "Start Time", "End Time"]


def chart(stage, date, start):
    return {"type": "series", "source": "Canyon chart",
            "meta": {"stage": stage, "date": date, "start_time": start}}


class _Tables:
    def __init__(self, rows):
        self.rows = rows

    def parse_interval_summary(self, doc):
        return {"columns": COLS, "rows": self.rows}


class CanyonDates(unittest.TestCase):

    def setUp(self):
        self._real = pipeline.canyon_tables

    def tearDown(self):
        pipeline.canyon_tables = self._real

    def _run(self, charts, rows):
        pipeline.canyon_tables = _Tables(rows)
        notes = []
        pipeline._canyon_dates(None, charts, notes)
        return [c["meta"]["date"] for c in charts], notes

    def test_one_header_date_is_the_jobs_start_and_the_summary_wins(self):
        dates, notes = self._run(
            [chart("1", "2014-10-12", "22:10:00"), chart("2", "2014-10-12", "03:05:00"),
             chart("3", "2014-10-12", "09:40:00")],
            [["1", "2014-10-12 22:09:00", ""], ["2", "2014-10-13 03:04:00", ""],
             ["3", "2014-10-14 09:41:00", ""]])
        self.assertEqual(dates, ["2014-10-12", "2014-10-13", "2014-10-14"])
        self.assertTrue(any("re-dated" in n for n in notes))

    def test_pages_that_date_themselves_keep_their_day(self):
        dates, notes = self._run(
            [chart("1", "2016-11-25", "16:41:52"), chart("11", "2016-11-26", "16:37:04"),
             chart("12", "2016-11-26", "17:14:21"), chart("13", "2016-11-27", "07:19:07")],
            [["1 (attempt 1)", "2016-11-25 16:42:23", ""],
             ["11", "2016-11-27 16:33:36", ""], ["12 (attempt 2)", "2016-11-27 17:11:27", ""],
             ["13", "2016-11-27 07:24:05", ""]])
        self.assertEqual(dates, ["2016-11-25", "2016-11-26", "2016-11-26", "2016-11-27"])
        self.assertTrue(any("keep the day their chart page prints" in n for n in notes))
        self.assertFalse(any("re-dated" in n for n in notes))

    def test_pages_and_summary_that_agree_say_nothing(self):
        dates, notes = self._run(
            [chart("1", "2017-08-27", "15:48:00"), chart("2", "2017-08-28", "01:10:00")],
            [["1", "2017-08-27 15:47:00", ""], ["2", "2017-08-28 01:09:00", ""]])
        self.assertEqual(dates, ["2017-08-27", "2017-08-28"])
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
