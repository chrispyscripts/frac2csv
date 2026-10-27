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


class PumpOnset(unittest.TestCase):
    def test_00261_a_page_that_opens_hours_before_its_first_zone(self):
        # "Zones 27-32" opens at 20:30 on the 17th; zone 27 is not pumped
        # until 01:00. Zone 26, on the page before, starts at 23:46.
        fl = dict(day_is="start", day_floor="2017-06-16",
                  day_ceil="2017-06-18")
        res = (_twins(26, "2017-06-17", "23:46:00", **fl)
               + _twins(27, "2017-06-17", "20:30:27", pump_offset_s=16200,
                        **fl)
               + _twins(28, "2017-06-18", "01:03:07", **fl))
        pipeline._calfrac_days(res, [])
        self.assertEqual(_days(res), {"26": ["2017-06-17"],
                                      "27": ["2017-06-17"],
                                      "28": ["2017-06-18"]})

    def test_the_onset_is_read_off_the_rate(self):
        import numpy as np
        import calfrac_progress as cp
        rate = np.zeros(1000)
        rate[100:400] = 6.0
        rate[600:900] = 6.0
        self.assertEqual(cp.pump_onset({"Slurry Rate": rate}, 0, 500), 100)
        self.assertEqual(cp.pump_onset({"Slurry Rate": rate}, 500, 1000),
                         100)
        self.assertEqual(cp.pump_onset({}, 0, 500), 0)


class PageHead(unittest.TestCase):
    """00261's "Zones 27-32" opens by re-plotting zones 21-26."""

    def _zone(self, stage, page, start, rate, first=False):
        import numpy as np
        r = _zone(stage, "2017-06-16", start, page=page, zone_span=6,
                  page_first=first)
        r["samples"] = np.arange(len(rate), dtype=float)
        r["data"] = {"Slurry Rate": np.asarray(rate, float)}
        return r

    def test_the_replotted_head_is_cut_at_the_break_after_the_zone_before(self):
        import numpy as np
        # zone 26 on p95: 23:46 for 43 min -> ends 00:29
        z26 = self._zone("26 BH", 95, "23:46:00", np.full(2580, 9.0))
        # zone 27 on p100 opens 20:30: treatments, a break at 00:26, its own
        rate = np.full(16380, 9.0)
        for b in (2400, 4800, 7200, 9600, 12000, 14160):   # every 40 min
            rate[b - 60:b + 60] = 0.0
        z27 = self._zone("27 BH", 100, "20:30:00", rate, first=True)
        notes = []
        pipeline._calfrac_page_heads([z26, z27], notes)
        self.assertEqual(z27["meta"]["start_time"], "00:26:00")
        self.assertEqual(len(z27["samples"]), 16380 - 14160)
        self.assertTrue(notes)

    def test_one_long_treatment_is_never_cut(self):
        import numpy as np
        z26 = self._zone("26 BH", 95, "23:46:00", np.full(2580, 9.0))
        z27 = self._zone("27 BH", 100, "23:40:00", np.full(5000, 9.0),
                         first=True)
        pipeline._calfrac_page_heads([z26, z27], [])
        self.assertEqual(z27["meta"]["start_time"], "23:40:00")


class ZoneRangePage(unittest.TestCase):
    def test_00258_a_whole_range_page_follows_the_zone_before_it(self):
        fl = dict(day_is="start", day_floor="2017-06-19")
        res = (_twins(1, "2017-06-19", "23:05:00", day_ceil="2017-06-20", **fl)
               + _twins(2, "2017-06-20", "00:44:54", day_ceil="2017-06-20",
                        **fl))
        whole = _zone("3-32 BH", "2017-06-19", "02:22:00", multi_zone=True,
                      day_ceil="2017-06-21", **fl)
        res.append(whole)
        pipeline._calfrac_days(res, [])
        self.assertEqual(whole["meta"]["date"], "2017-06-20")

    def test_a_range_page_with_nothing_before_it_is_left_alone(self):
        # 00218's first attempt, "1-3" on Feb 9
        whole = _zone("1-3 BH", "2017-02-09", "03:40:00", multi_zone=True)
        res = (_twins(1, "2017-02-28", "19:38:00")
               + _twins(2, "2017-02-28", "20:23:00") + [whole])
        pipeline._calfrac_days(res, [])
        self.assertEqual(whole["meta"]["date"], "2017-02-09")


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

    def test_a_later_chart_of_the_zone_keeps_its_blank(self):
        # 00257: "Zone 5" on p100-101, "Zone 5 Well Flush" on p105-106,
        # both behind the same sheets
        times = {78: {5: {"start": "14:35"}}}
        treat = _twins(5, "", "00:00:00")
        treat[0]["page"], treat[1]["page"] = 100, 101
        flush = _twins(5, "", "00:00:00")
        flush[0]["page"], flush[1]["page"] = 105, 106
        pipeline._calfrac_sheet_clocks(treat + flush, [], times,
                                       {78: "2017-06-09"})
        self.assertEqual([r["meta"]["start_time"] for r in treat],
                         ["14:35:00", "14:35:00"])
        self.assertEqual([r["meta"]["start_time"] for r in flush],
                         ["00:00:00", "00:00:00"])

    def test_a_sheet_dated_after_the_chart_was_exported_is_not_its_own(self):
        # 00277: a Dec 9 2016 "Zones 1-5" attempt in front of Jan 2017 sheets
        whole = _zone("1-5 BH", "", "00:00:00", page=47, multi_zone=True,
                      day_ceil="2016-12-09")
        pipeline._calfrac_sheet_clocks([whole], [], {44: {1: {"start": "1:00"}}},
                                       {44: "2017-01-05"})
        self.assertEqual(whole["meta"]["start_time"], "00:00:00")
        self.assertEqual(whole["meta"]["date"], "")

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
