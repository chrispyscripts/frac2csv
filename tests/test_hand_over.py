"""Charts that run on into the next stage, and the whole-job re-plots (00041, #645).

  python3 -m unittest tests.test_hand_over
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                            # noqa: E402

SRC = "Trican treatment chart (raster)"


def series(stage, date, start, minutes, press, rate=None, source=SRC, **meta):
    n = int(minutes * 60)
    md = {"title": f"Stage {stage}", "stage": str(stage), "date": date,
          "start_time": start, "duration_min": minutes, "warnings": []}
    md.update(meta)
    data = {"Tr Press": np.asarray(press, float)[:n]}
    if rate is not None:
        data["Slurry Rate"] = np.asarray(rate, float)[:n]
    return pipeline._series(md, np.arange(n, dtype=float), data, source, page=1)


def ramp(n, a, b):
    return np.linspace(a, b, n)


class NearestDate(unittest.TestCase):

    def test_sheet_two_minutes_late_same_day(self):
        # 00041 p73: sheet 21:40, chart 21:38
        self.assertEqual(pipeline._nearest_date("2015-11-12", 21 * 3600 + 40 * 60,
                                                21 * 3600 + 38 * 60), "2015-11-12")

    def test_sheet_after_midnight_chart_before_it(self):
        self.assertEqual(pipeline._nearest_date("2015-11-13", 60,
                                                23 * 3600 + 58 * 60), "2015-11-12")

    def test_sheet_twelve_hours_wrong_stays_on_its_day(self):
        # 00041 p117: sheet 12:00, chart 06:22 — the 14th either way
        self.assertEqual(pipeline._nearest_date("2015-11-14", 12 * 3600,
                                                6 * 3600 + 22 * 60), "2015-11-14")

    def test_no_sheet_time_keeps_the_sheet_date(self):
        self.assertEqual(pipeline._nearest_date("2015-11-14", None, 5), "2015-11-14")


class AbsStart(unittest.TestCase):

    def test_midnight_is_unread_unless_the_chart_read_it(self):
        r = series(1, "2015-11-12", "00:00:00", 5, np.zeros(300))
        self.assertIsNone(pipeline._abs_start(r))
        r["meta"]["clock_chart"] = True
        self.assertEqual(pipeline._abs_start(r).hour, 0)

    def test_undated_is_unread(self):
        r = series(1, "", "07:17:00", 5, np.zeros(300))
        self.assertIsNone(pipeline._abs_start(r))


class HandOver(unittest.TestCase):
    """Stage 1 07:17 for 70 min, stage 2 08:23: the last 4 min of one are
    the first 4 of the other, drawn from one job-long trace."""

    def setUp(self):
        job = 40.0 + 20.0 * np.sin(np.arange(200 * 60) / 300.0)     # the well
        self.job = job
        self.a = series(1, "2015-11-12", "07:17:00", 70, job[0:70 * 60])
        self.b = series(2, "2015-11-12", "08:23:00", 60, job[66 * 60:126 * 60])

    def test_same_minutes_hand_over(self):
        notes = []
        pipeline._hand_over_tails([self.a, self.b], notes)
        self.assertEqual(len(self.a["samples"]), 66 * 60)
        self.assertEqual(len(self.a["data"]["Tr Press"]), 66 * 60)
        self.assertAlmostEqual(self.a["meta"]["duration_min"], 66.0)
        self.assertEqual(len(self.b["samples"]), 60 * 60)          # untouched
        self.assertTrue(any("hands over" in w for w in self.a["meta"]["warnings"]))
        self.assertTrue(any("cut where the next chart begins" in n for n in notes))

    def test_different_minutes_are_kept_and_said(self):
        # stage 2's chart shows something else over those four minutes
        self.b["data"]["Tr Press"] = self.b["data"]["Tr Press"] + 30.0
        notes = []
        pipeline._hand_over_tails([self.a, self.b], notes)
        self.assertEqual(len(self.a["samples"]), 70 * 60)
        self.assertTrue(any("disagree" in w for w in self.a["meta"]["warnings"]))
        self.assertTrue(any("disagree" in n for n in notes))

    def test_no_overlap_nothing_happens(self):
        self.b["meta"]["start_time"] = "08:28:00"
        notes = []
        pipeline._hand_over_tails([self.a, self.b], notes)
        self.assertEqual(len(self.a["samples"]), 70 * 60)
        self.assertEqual(notes, [])

    def test_unclocked_stages_are_left_alone(self):
        self.b["meta"]["start_time"] = "00:00:00"
        notes = []
        pipeline._hand_over_tails([self.a, self.b], notes)
        self.assertEqual(len(self.a["samples"]), 70 * 60)

    def test_sources_do_not_hand_over_to_each_other(self):
        self.b["source"] = "STEP chart"
        notes = []
        pipeline._hand_over_tails([self.a, self.b], notes)
        self.assertEqual(len(self.a["samples"]), 70 * 60)

    def test_two_thirds_of_the_channels_must_agree(self):
        job = self.job
        a = series(1, "2015-11-12", "07:17:00", 70, job[0:70 * 60], rate=job[0:70 * 60])
        b = series(2, "2015-11-12", "08:23:00", 60, job[66 * 60:126 * 60],
                   rate=job[66 * 60:126 * 60] + 30.0)
        pipeline._hand_over_tails([a, b], [])
        self.assertEqual(len(a["samples"]), 70 * 60)                # 1 of 2 is not enough
        c = series(2, "2015-11-12", "08:23:00", 60, job[66 * 60:126 * 60],
                   rate=job[66 * 60:126 * 60])
        pipeline._hand_over_tails([a, c], [])
        self.assertEqual(len(a["samples"]), 66 * 60)

    def test_a_flat_channel_says_nothing(self):
        # both charts show zero rate over the overlap: not evidence either way
        a = series(1, "2015-11-12", "07:17:00", 70, np.zeros(70 * 60))
        b = series(2, "2015-11-12", "08:23:00", 60, np.zeros(60 * 60))
        notes = []
        pipeline._hand_over_tails([a, b], notes)
        self.assertEqual(len(a["samples"]), 70 * 60)
        self.assertEqual(notes, [])


class FiledToTheMinute(unittest.TestCase):
    """00180: the Daily Stage Summary files starts to the minute, and stage
    6's window opened half a minute before its filed 08:23."""

    def setUp(self):
        # white noise: aperiodic, so exactly one lag lines the two charts up
        # (a sine would match again every period); 90 minutes so a stage 5
        # of 70 min leaves fifteen minutes of reach either way
        self.job = 40.0 + 10.0 * np.random.default_rng(7).normal(size=400 * 60)
        self.a = series(5, "2016-11-11", "07:17:00", 70, self.job[0:70 * 60])

    def b_opening_at(self, offset_s, filed="08:23:00", minutes=60, **meta):
        # B's data really begins 66 min + offset after A's; filed at 08:23
        start = 66 * 60 + offset_s
        return series(6, "2016-11-11", filed, minutes,
                      self.job[start:start + minutes * 60], **meta)

    def test_half_a_minute_early_is_found_moved_and_cut(self):
        b = self.b_opening_at(-30)
        notes = []
        pipeline._hand_over_tails([self.a, b], notes)
        self.assertEqual(b["meta"]["start_time"], "08:22:30")
        self.assertEqual(b["meta"]["date"], "2016-11-11")
        self.assertEqual(len(self.a["samples"]), 66 * 60 - 30)
        self.assertTrue(any("start moved -30 s (08:23:00 → 08:22:30)" in w
                            for w in b["meta"]["warnings"]))
        self.assertTrue(any("moved by up to 30 s" in n for n in notes))
        self.assertTrue(any("cut where the next chart begins" in n for n in notes))

    def test_late_is_found_too(self):
        b = self.b_opening_at(+45)
        pipeline._hand_over_tails([self.a, b], [])
        self.assertEqual(b["meta"]["start_time"], "08:23:45")
        self.assertEqual(len(self.a["samples"]), 66 * 60 + 45)

    def test_a_move_across_midnight_carries_the_day(self):
        a = series(5, "2016-11-11", "23:00:00", 70, self.job[0:70 * 60])
        b = series(6, "2016-11-11", "23:59:50", 60, self.job[60 * 60 + 20:])   # opens 00:00:20
        pipeline._hand_over_tails([a, b], [])
        self.assertEqual((b["meta"]["date"], b["meta"]["start_time"]), ("2016-11-12", "00:00:20"))

    def test_beyond_reach_is_left_and_said(self):
        b = self.b_opening_at(-1000)                         # more than fifteen minutes
        notes = []
        pipeline._hand_over_tails([self.a, b], notes)
        self.assertEqual(b["meta"]["start_time"], "08:23:00")
        self.assertEqual(len(self.a["samples"]), 70 * 60)
        self.assertTrue(any("disagree" in n for n in notes))

    def test_a_chart_that_printed_its_own_clock_moves_a_minute_at_most(self):
        b = self.b_opening_at(-90, clock_chart=True)
        pipeline._hand_over_tails([self.a, b], [])
        self.assertEqual(b["meta"]["start_time"], "08:23:00")
        self.assertEqual(len(self.a["samples"]), 70 * 60)
        c = self.b_opening_at(-40, clock_chart=True)
        pipeline._hand_over_tails([self.a, c], [])
        self.assertEqual(c["meta"]["start_time"], "08:22:20")

    def test_the_next_pair_starts_from_the_moved_chart(self):
        b = self.b_opening_at(-30)
        c = series(7, "2016-11-11", "09:20:00", 60,
                   self.job[(66 * 60 - 30) + 57 * 60:])       # opens 57 min after B's true start
        pipeline._hand_over_tails([self.a, b, c], [])
        self.assertEqual(b["meta"]["start_time"], "08:22:30")
        self.assertEqual(c["meta"]["start_time"], "09:19:30")
        self.assertEqual(len(b["samples"]), 57 * 60)


    def test_the_search_follows_the_drift(self):
        # b sits 800 s past its filed start, c 1500 s past its own: beyond
        # reach from zero, within reach of the lag b settled on
        # windows long enough that each chart still reaches the next one's
        # true opening: a runs 90 min, b 75
        a = series(5, "2016-11-11", "07:17:00", 90, self.job[0:90 * 60])
        b = self.b_opening_at(+800, minutes=75)
        c = series(7, "2016-11-11", "09:20:00", 60,
                   self.job[(66 * 60 + 800) + 57 * 60 + 700:])   # 57 min after b, filed 08:23+57
        notes = []
        pipeline._hand_over_tails([a, b, c], notes)
        self.assertEqual(b["meta"]["start_time"], "08:36:20")
        self.assertEqual(c["meta"]["start_time"], "09:45:00")   # 09:20 + 1500 s
        self.assertTrue(any("drift apart" in n for n in notes))


class Continuous(unittest.TestCase):

    def setUp(self):
        job = 40.0 + 20.0 * np.sin(np.arange(400 * 60) / 300.0)
        self.s1 = series(1, "2015-11-12", "07:17:00", 70, job[0:70 * 60], clock_chart=True)
        self.s2 = series(2, "2015-11-12", "08:23:00", 60, job[66 * 60:126 * 60], clock_chart=True)

    def cont(self, start, minutes, **meta):
        r = series("", "", start, minutes, np.zeros(int(minutes * 60)), clock_chart=True,
                   continuous=True, **meta)
        r["meta"]["title"] = "Whole job (continuous)"
        r["page"] = 119
        return r

    def test_covered_replot_is_dropped_and_said(self):
        c = self.cont("07:17:00", 126)
        results, notes = [self.s1, self.s2, c], []
        pipeline._trican_continuous(results, notes)
        self.assertEqual(results, [self.s1, self.s2])
        self.assertTrue(any("CONTINUOUS chart(s) not exported (p119)" in n for n in notes))

    def test_minutes_no_stage_has_keep_it_and_date_it(self):
        c = self.cont("07:17:00", 200)                    # 74 min past stage 2
        results, notes = [self.s1, self.s2, c], []
        pipeline._trican_continuous(results, notes)
        self.assertIn(c, results)
        self.assertEqual(c["meta"]["date"], "2015-11-12")
        self.assertTrue(any("kept as a stage of its own" in n and "74 min" in n
                            for n in notes))

    def test_unclocked_is_kept(self):
        c = self.cont("00:00:00", 126)
        del c["meta"]["clock_chart"]
        results, notes = [self.s1, self.s2, c], []
        pipeline._trican_continuous(results, notes)
        self.assertIn(c, results)
        self.assertTrue(any("no clock" in n for n in notes))

    def test_no_stage_nearby_is_kept(self):
        c = self.cont("15:00:00", 60)
        results, notes = [self.s1, self.s2, c], []
        pipeline._trican_continuous(results, notes)
        self.assertIn(c, results)
        self.assertEqual(c["meta"]["date"], "")

    def test_hand_over_ignores_continuous(self):
        c = self.cont("07:17:00", 126)
        c["meta"]["date"] = "2015-11-12"
        pipeline._hand_over_tails([self.s1, self.s2, c], [])
        self.assertEqual(len(c["samples"]), 126 * 60)


if __name__ == "__main__":
    unittest.main()
