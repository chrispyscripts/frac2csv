"""Trican books printed as pictures (00327, AER Duvernay, #807).

  python3 -m unittest tests.test_trican_scanned
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402
import trican_charts as tc                               # noqa: E402


class SheetStartOCR(unittest.TestCase):
    def test_the_start_times_as_the_ocr_gives_them(self):
        for raw, want in (("Start Time: Nov 08, 0452 PM", ("Nov", "08", "04", "52", "P")),
                          ("Start Time: Nov 09, 09 35 AM", ("Nov", "09", "09", "35", "A")),
                          ("Start Time: Nov 10,0903 AM W", ("Nov", "10", "09", "03", "A")),
                          ("Start Time: Nov 12, 1134PM W", ("Nov", "12", "11", "34", "P"))):
            self.assertEqual(tc._SCAN_START.search(raw).groups(), want)

    def test_the_cover_gives_the_year(self):
        m = tc._SCAN_COVER.search("ARTIS HZ HUXLEY 100/03-29-035-24W4, STAGE 2-7, NOV 9, 2019 **** TIGHT")
        self.assertEqual(m.group(3), "2019")


def stage(n, start, mins, sheet=None):
    d = datetime.fromisoformat(start)
    md = {"stage": str(n), "date": d.date().isoformat(), "start_time": d.strftime("%H:%M:%S"),
          "clock_chart": True}
    if sheet:
        s = datetime.fromisoformat(sheet)
        md["sheet_date"], md["sheet_start"] = s.date().isoformat(), s.strftime("%H:%M:%S")
    return {"type": "series", "source": "Trican treatment chart (raster)", "page": n,
            "meta": md, "samples": np.arange(mins * 60, dtype=float)}


class StageOrder(unittest.TestCase):
    def test_a_chart_clock_on_the_wrong_day_moves_a_day(self):
        # 00327 stage 19: chart 17:19, dated to the day before stage 18
        rs = [stage(18, "2019-11-12T04:12", 139), stage(19, "2019-11-11T17:19", 229, "2019-11-12T00:00"),
              stage(20, "2019-11-12T23:34", 150)]
        self.assertEqual(pipeline._trican_order(rs, []), 1)
        self.assertEqual((rs[1]["meta"]["date"], rs[1]["meta"]["start_time"]), ("2019-11-12", "17:19:00"))

    def test_a_chart_printing_the_next_stages_clock_takes_its_sheet(self):
        # 00327 stage 5: chart 19:36 (stage 6's window), sheet 14:25
        rs = [stage(4, "2019-11-09T09:35", 148), stage(5, "2019-11-09T19:36", 90, "2019-11-09T14:25"),
              stage(6, "2019-11-09T19:41", 85, "2019-11-09T19:47")]
        pipeline._trican_order(rs, [])
        self.assertEqual(rs[1]["meta"]["start_time"], "14:25:00")
        self.assertEqual(rs[2]["meta"]["start_time"], "19:41:00")

    def test_stages_in_order_are_left_alone(self):
        rs = [stage(1, "2019-11-08T17:42", 171), stage(2, "2019-11-08T23:53", 153),
              stage(3, "2019-11-09T04:43", 134)]
        self.assertEqual(pipeline._trican_order(rs, []), 0)


if __name__ == "__main__":
    unittest.main()
