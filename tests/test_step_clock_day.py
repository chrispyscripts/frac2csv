"""A STEP chart that prints a wall clock but no day (00243, 00197).

_step_clock gives such a chart the Daily Stage Summary's day for its stage.
It took the day nearest the filed start, and for a stage that runs most of a
day that is the wrong one. step1 now also says which STEP charts read their
own clock, and those are moved by a hand-over by the label's precision only
(HANDOVER_SELF_S), not the fifteen minutes a start filed to the minute gets.

Run: python3 -m unittest tests.test_step_clock_day
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                            # noqa: E402


def chart(stage, start, minutes):
    n = int(minutes * 60)
    md = {"title": f"Interval {stage}", "stage": str(stage), "date": "",
          "start_time": start, "duration_min": minutes, "warnings": [],
          "clock_chart": True}
    return pipeline._series(md, np.arange(n, dtype=float),
                            {"Tr Press": np.full(n, 40.0)},
                            "STEP surface chart (raster)", page=77)


class ClockedButUndated(unittest.TestCase):
    """00243 stage 30: filed 2017-09-01 00:26 to 23:32 ("got back into
    stage"), its chart printing a wall clock of 21:00-23:15 and no date. The
    nearest day to the filed start put it on 08-31, before stage 29 (filed
    08-31 21:57) had begun, and the Lab said 30 started 160 min before 29
    finished. The day is the one between the stages either side."""

    CLOCKS = {"29": {"date": "2017-08-31", "start": "21:57:00"},
              "30": {"date": "2017-09-01", "start": "00:26:00"},
              "31": {"date": "2017-09-01", "start": "23:32:00"}}

    def test_the_day_between_its_neighbours(self):
        self.assertEqual(pipeline._step_day_between(
            self.CLOCKS, "30", 20 * 3600 + 59 * 60 + 34), "2017-09-01")

    def test_no_neighbour_no_answer(self):
        self.assertIsNone(pipeline._step_day_between(
            {"30": self.CLOCKS["30"]}, "30", 75600))

    def test_through_step_clock(self):
        r = chart(30, "20:59:34", 30)
        was = pipeline.step_summary.stage_clock
        pipeline.step_summary.stage_clock = lambda doc: self.CLOCKS
        try:
            pipeline._step_clock(None, [r], [])
        finally:
            pipeline.step_summary.stage_clock = was
        self.assertEqual(r["meta"]["date"], "2017-09-01")

    def test_a_clock_near_its_filed_start_keeps_the_nearest_day(self):
        # 00:10 for a stage filed 00:26: the day it was filed
        self.assertEqual(pipeline._step_day_between(
            self.CLOCKS, "30", 600), "2017-09-01")


if __name__ == "__main__":
    unittest.main()
