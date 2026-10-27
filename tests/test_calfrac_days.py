"""Putting a CalFrac well's zones on the right DAY.

MView prints every zone twice — a "Surface" and a "Bottom Hole" chart — and
the reader keeps them apart as "12 Surface" / "12 BH". _calfrac_days keyed
on that label, so each zone was two entries with one start time, which no
strictly increasing order can hold: on every twinned well the day fit failed
and the stages kept whatever their pages printed. 00192's zone 11 (01:18)
stayed on the day zone 10 (23:31) ran; 00188 ran zones 7-35 on its first day.

And a sheet whose Job Date is a range ("08/20/2017 - 08/22/2017") states the
job's first day. Without that floor the fit on 00192 preferred moving ten
zones back to 08-19 over moving twenty-five on to 08-21.

Charts of a single zone ("Zone 19") never went through a split page and had
no clock at all; their start is on the Multiple-Zone sheet in front of them.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                          # noqa: E402


def _zone(stage, date, start, page=1, **meta):
    md = {"stage": stage, "date": date, "start_time": start, "warnings": []}
    md.update(meta)
    return {"type": "series", "source": "CalFrac chart", "meta": md,
            "page": page}


def _twins(zone, date, start, **meta):
    return [_zone(f"{zone} Surface", date, start, **meta),
            _zone(f"{zone} BH", date, start, **meta)]


def _days(results):
    out = {}
    for r in results:
        out.setdefault(r["meta"]["stage"].split()[0], set()).add(
            r["meta"]["date"])
    return {k: sorted(v) for k, v in out.items()}


class TwinsAreOneZone(unittest.TestCase):
    def test_00192_shape_counts_forward_from_the_job_start(self):
        # zones 1-2 on the 20th, 3 at 23:31, then 4-5 after midnight; all
        # sheets "08/20/2017 - 08/22/2017"; zone 6 rolled within its page
        start = dict(day_is="start", day_floor="2017-08-20")
        res = (_twins(1, "2017-08-20", "01:35:13", **start)
               + _twins(2, "2017-08-20", "16:45:00", **start)
               + _twins(3, "2017-08-20", "23:31:00", **start)
               + _twins(4, "2017-08-20", "01:18:20", **start)
               + _twins(5, "2017-08-20", "22:23:00", **start)
               + _twins(6, "2017-08-21", "00:35:11", **start))
        notes = []
        pipeline._calfrac_days(res, notes)
        self.assertEqual(_days(res), {
            "1": ["2017-08-20"], "2": ["2017-08-20"], "3": ["2017-08-20"],
            "4": ["2017-08-21"], "5": ["2017-08-21"], "6": ["2017-08-22"]})
        self.assertTrue(any("re-dated" in n for n in notes), notes)

    def test_without_a_floor_the_fewest_pages_move(self):
        # the same well with single-date sheets: moving the two early zones
        # back a day is cheaper than moving three forward, and nothing says
        # the job had begun by the 20th
        start = dict(day_is="start")
        res = (_twins(1, "2017-08-20", "01:35:13", **start)
               + _twins(2, "2017-08-20", "23:31:00", **start)
               + _twins(3, "2017-08-20", "01:18:20", **start)
               + _twins(4, "2017-08-20", "22:23:00", **start)
               + _twins(5, "2017-08-21", "00:35:11", **start))
        pipeline._calfrac_days(res, [])
        self.assertEqual(_days(res), {
            "1": ["2017-08-19"], "2": ["2017-08-19"], "3": ["2017-08-20"],
            "4": ["2017-08-20"], "5": ["2017-08-21"]})

    def test_a_rerun_of_a_zone_hours_later_is_its_own_entry(self):
        # 00223: zone 1 flushed on the 12th and again on the 13th
        res = (_twins(1, "2017-03-12", "12:50:00", day_is="start")
               + _twins(1, "2017-03-13", "16:34:00", day_is="start")
               + _twins(2, "2017-03-18", "16:30:00", day_is="start"))
        pipeline._calfrac_days(res, [])
        self.assertEqual(_days(res), {"1": ["2017-03-12", "2017-03-13"],
                                      "2": ["2017-03-18"]})

    def test_twins_a_few_seconds_apart_still_pair(self):
        fl = dict(day_is="start", day_floor="2017-08-13")
        res = [_zone("1 Surface", "2017-08-13", "22:00:00", **fl),
               _zone("1 BH", "2017-08-13", "22:00:04", **fl),
               _zone("2 Surface", "2017-08-13", "01:00:00", **fl),
               _zone("2 BH", "2017-08-13", "01:00:03", **fl),
               _zone("3 Surface", "2017-08-14", "03:00:00", **fl),
               _zone("3 BH", "2017-08-14", "03:00:01", **fl)]
        pipeline._calfrac_days(res, [])
        self.assertEqual(_days(res)["2"], ["2017-08-14"])


class ExportDateCeiling(unittest.TestCase):
    def test_00224_shape_a_sheet_dated_by_its_later_zones(self):
        # Mar 8 sheet: zones 1-2, chart exported 3/8. Mar 9 sheet: zone 3 at
        # 22:59 (the evening of the 8th), zones 4-5 after midnight, which the
        # split rolled to the 10th; chart exported 3/9. Zone 6 alone on a
        # Mar 9 sheet at 00:02, chart exported 3/10.
        res = (_twins(1, "2017-03-08", "18:21:30", day_is="start",
                      day_ceil="2017-03-08")
               + _twins(2, "2017-03-08", "21:45:58", day_is="start",
                        day_ceil="2017-03-08")
               + _twins(3, "2017-03-09", "22:59:56", day_is="start",
                        day_ceil="2017-03-09")
               + _twins(4, "2017-03-10", "00:09:03", day_is="start",
                        day_ceil="2017-03-09")
               + _twins(5, "2017-03-10", "10:06:58", day_is="start",
                        day_ceil="2017-03-09")
               + _twins(6, "2017-03-09", "00:02:00", day_is="start",
                        day_ceil="2017-03-10"))
        pipeline._calfrac_days(res, [])
        self.assertEqual(_days(res), {
            "1": ["2017-03-08"], "2": ["2017-03-08"], "3": ["2017-03-08"],
            "4": ["2017-03-09"], "5": ["2017-03-09"], "6": ["2017-03-10"]})

    def test_a_stamp_the_order_cannot_meet_is_ignored(self):
        # a footer earlier than the job's own first day is not an export date
        res = (_twins(1, "2017-08-20", "22:00:00", day_floor="2017-08-20",
                      day_ceil="2017-08-01")
               + _twins(2, "2017-08-20", "01:00:00", day_floor="2017-08-20",
                        day_ceil="2017-08-01"))
        pipeline._calfrac_days(res, [])
        self.assertEqual(_days(res), {"1": ["2017-08-20"],
                                      "2": ["2017-08-21"]})


class Reprints(unittest.TestCase):
    def _page(self, stage, mv, page, vals):
        import numpy as np
        r = _zone(stage, "", "00:00:00", page=page, mv=mv)
        r["samples"] = np.arange(len(vals), dtype=float)
        r["data"] = {"Tr Press": np.array(vals, float)}
        return r

    def test_00223_a_reprinted_sheet_is_read_once(self):
        a = self._page("2 Surface", " Surface", 117, [1, 2, 3])
        b = self._page("2 BH", " BH", 118, [4, 5, 6])
        c = self._page("2 Surface", " Surface", 123, [1, 2, 3])
        d = self._page("2 BH", " BH", 124, [4, 5, 6])
        res, notes = [a, b, c, d], []
        pipeline._calfrac_reprints(res, notes)
        self.assertEqual([r["page"] for r in res], [117, 118])
        self.assertIn("p123 = p117", notes[0])

    def test_a_real_retreat_is_kept(self):
        a = self._page("2 Surface", " Surface", 117, [1, 2, 3])
        c = self._page("2 Surface", " Surface", 123, [1, 2, 4])
        res = [a, c]
        pipeline._calfrac_reprints(res, [])
        self.assertEqual(len(res), 2)


class FitFloors(unittest.TestCase):
    def test_a_floor_rules_out_moving_back(self):
        d = 736561
        days = [d, d, d, d + 1]
        secs = [3600, 80000, 3000, 2000]
        self.assertEqual(pipeline._calfrac_day_fit(days, secs),
                         [d - 1, d - 1, d, d + 1])
        self.assertEqual(pipeline._calfrac_day_fit(days, secs, [d] * 4),
                         [d, d, d + 1, d + 2])

    def test_no_floor_is_the_old_fit(self):
        d = 736561
        self.assertEqual(pipeline._calfrac_day_fit([d, d], [5, 4]),
                         pipeline._calfrac_day_fit([d, d], [5, 4],
                                                   [None, None]))


class SheetClocks(unittest.TestCase):
    TIMES = {96: {19: {"start": "23:06", "stop": "1:36"}}}

    def test_a_single_zone_chart_takes_its_sheets_clock(self):
        res = _twins(19, "", "00:00:00", page=98)
        notes = []
        pipeline._calfrac_sheet_clocks(res, notes, self.TIMES,
                                       {96: "2017-03-04"})
        for r in res:
            self.assertEqual(r["meta"]["start_time"], "23:06:00")
            self.assertEqual(r["meta"]["date"], "2017-03-04")
            self.assertEqual(r["meta"]["day_is"], "start")
        self.assertEqual(len(notes), 1)
        self.assertIn(": 19", notes[0])           # one zone, not two sheets

    def test_split_zones_and_printed_clocks_are_left_alone(self):
        split = _zone("19 BH", "2017-03-05", "01:00:00", page=98,
                      zone_span=4)
        printed = _zone("19 Surface", "2017-03-05", "02:00:00", page=98,
                        clock_chart=True)
        pipeline._calfrac_sheet_clocks([split, printed], [], self.TIMES,
                                       {96: "2017-03-04"})
        self.assertEqual(split["meta"]["start_time"], "01:00:00")
        self.assertEqual(printed["meta"]["start_time"], "02:00:00")


if __name__ == "__main__":
    unittest.main()
