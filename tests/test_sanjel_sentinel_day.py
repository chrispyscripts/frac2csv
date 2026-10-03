"""A Sanjel chart that prints a clock but no DAY (00100 p37, interval 19).

These sheets print the day in the header and the clock on the time axis, read
independently. 00100 p37 heads interval 19 "January 0, 1900" -- Excel's
empty-date sentinel -- which sanjel.py refuses outright and should: v1.11.3
shipped that refusal because believing it put a stage a century off.

But the page's TIME axis is good. It runs 20:37:16 to 21:22:16, and only the
day was ever missing. Losing the day lost the clock with it, because
everything downstream keys a stage on a full timestamp, so interval 19
arrived with no time at all and FracView PLACED it -- after interval 18, at
20:42 -- when the sheet says 20:37. Carmine: "stage 19 ... the time needs to
be adjusted".

  python3 -m unittest tests.test_sanjel_sentinel_day
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                               # noqa: E402


def chart(page, stage, date, start):
    return {"type": "series", "source": "Sanjel chart", "page": page,
            "meta": {"stage": stage, "date": date, "start_time": start}}


def run(rows):
    notes = []
    pipeline._sanjel_dates(rows, notes)
    return rows, notes


class TakesTheDayAround(unittest.TestCase):

    def test_00100_interval_19(self):
        """18 and 20 agree on the day and bracket 19's clock."""
        rows, notes = run([chart(36, "18", "2016-01-28", "19:57:16"),
                           chart(37, "19", "", "20:37:16"),
                           chart(38, "20", "2016-01-28", "21:19:16")])
        self.assertEqual(rows[1]["meta"]["date"], "2016-01-28")
        self.assertEqual(rows[1]["meta"]["start_time"], "20:37:16",
                         "the TIME is the chart's own and is never rewritten")
        self.assertTrue(notes and "empty-date sentinel" in notes[0])

    def test_the_dated_charts_are_not_touched(self):
        rows, _ = run([chart(36, "18", "2016-01-28", "19:57:16"),
                       chart(37, "19", "", "20:37:16"),
                       chart(38, "20", "2016-01-28", "21:19:16")])
        self.assertEqual(rows[0]["meta"]["date"], "2016-01-28")
        self.assertEqual(rows[2]["meta"]["date"], "2016-01-28")

    def test_it_reaches_past_another_undated_chart(self):
        rows, _ = run([chart(1, "1", "2016-01-28", "01:00:00"),
                       chart(2, "2", "", "02:00:00"),
                       chart(3, "3", "", "03:00:00"),
                       chart(4, "4", "2016-01-28", "04:00:00")])
        self.assertEqual([r["meta"]["date"] for r in rows],
                         ["2016-01-28"] * 4)


class WhatItRefuses(unittest.TestCase):

    def test_neighbours_on_different_days(self):
        """A run spanning midnight: which day is a guess, so it is not made."""
        rows, notes = run([chart(1, "1", "2016-01-28", "23:00:00"),
                           chart(2, "2", "", "00:30:00"),
                           chart(3, "3", "2016-01-29", "02:00:00")])
        self.assertEqual(rows[1]["meta"]["date"], "")
        self.assertEqual(notes, [])

    def test_a_clock_outside_its_neighbours(self):
        """19:00 does not sit between 20:00 and 21:00 — it has wrapped, or it
        is not where the page order says. Either way it is not a reading."""
        rows, _ = run([chart(1, "1", "2016-01-28", "20:00:00"),
                       chart(2, "2", "", "19:00:00"),
                       chart(3, "3", "2016-01-28", "21:00:00")])
        self.assertEqual(rows[1]["meta"]["date"], "")

    def test_nothing_dated_on_one_side(self):
        rows, _ = run([chart(1, "1", "", "20:00:00"),
                       chart(2, "2", "", "20:37:00"),
                       chart(3, "3", "2016-01-28", "21:00:00")])
        self.assertEqual(rows[0]["meta"]["date"], "")
        self.assertEqual(rows[1]["meta"]["date"], "")

    def test_a_chart_with_no_clock_at_all(self):
        rows, _ = run([chart(1, "1", "2016-01-28", "20:00:00"),
                       chart(2, "2", "", ""),
                       chart(3, "3", "2016-01-28", "21:00:00")])
        self.assertEqual(rows[1]["meta"]["date"], "")

    def test_other_templates_are_not_touched(self):
        rows, notes = run([chart(1, "1", "2016-01-28", "20:00:00"),
                           {"type": "series", "source": "Liberty chart",
                            "page": 2,
                            "meta": {"stage": "2", "date": "", "start_time": "20:37:00"}},
                           chart(3, "3", "2016-01-28", "21:00:00")])
        self.assertEqual(rows[1]["meta"]["date"], "")
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
