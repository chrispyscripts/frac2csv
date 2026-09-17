"""Trican layout B: the clock ladder with misread hours, and the window
the page prints around the stage.

  python3 -m unittest tests.test_trican_b_clock

The label sets are the ones OCR actually handed back on the seven pages
that died of "implausible stage duration" (#625, #640): this font's 9 reads
as 3, the minutes never wrong. The window shapes are 01433 p155 (13.5 h
around a one-hour stage 1) and p213 (two hours around a 34-minute stage 60).
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc                                # noqa: E402

X0, X1 = 59, 791


def hm(s):
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def fit_span(labels, hint=None):
    pts = [(hm(t), x) for t, x in labels]
    a, b = tc._b_clock_fit(pts, X0, X1, hm(hint) if hint else None)
    return a + b * X0, b * (X1 - X0)              # start, duration over the plot


class MisreadHours(unittest.TestCase):

    def test_01433_p157_nine_read_as_three(self):
        # 18:50 13:00 13:10 19:20 13:30 19:40 19:50 20:00 — three 19s read as 13
        start, dur = fit_span([("18:50", 83), ("13:00", 172), ("13:10", 262), ("19:20", 352),
                               ("13:30", 441), ("19:40", 531), ("19:50", 620), ("20:00", 710)])
        self.assertAlmostEqual(start / 60, hm("18:47") / 60, delta=1.0)     # 18:47 at the frame
        self.assertAlmostEqual(dur / 60, 82, delta=2)                      # 82 min, not 240455 s

    def test_01421_p178_the_misread_is_the_majority(self):
        # four 03s against three 09s: the minutes cannot decide, the page's
        # printed "Start Time 09:25" can
        labels = [("09:25", 136), ("03:30", 244), ("03:35", 352), ("03:40", 462),
                  ("09:45", 569), ("03:50", 678), ("09:55", 785)]
        start, dur = fit_span(labels, hint="09:25")
        self.assertAlmostEqual(start / 60, hm("09:21") / 60, delta=1.0)
        self.assertAlmostEqual(dur / 60, 34, delta=1.5)
        # and without the hint the duration is still right — only the hour is open
        _start, dur2 = fit_span(labels)
        self.assertAlmostEqual(dur2 / 60, 34, delta=1.5)

    def test_a_tie_between_the_two_swaps_is_decided_by_the_font(self):
        # The ladder above with no printed start: "every 3 is really a 9" and
        # "every 9 is really a 3" explain all seven labels equally, and scored
        # bit-for-bit identically — same inliers, same recovered count, no
        # hint, and a slope equal to the last bit. The winner was whichever
        # the candidate list held first, which is not a decision: it came back
        # 09:21 here and 03:21 on CI, where a different LAPACK rounds the
        # slope the other way. The font only misreads 9 as 3, so 3 -> 9 is the
        # recovery and 9 -> 3 is not; that is what settles it now.
        labels = [("09:25", 136), ("03:30", 244), ("03:35", 352), ("03:40", 462),
                  ("09:45", 569), ("03:50", 678), ("09:55", 785)]
        start, _ = fit_span(labels)
        self.assertAlmostEqual(start / 60, hm("09:21") / 60, delta=1.0)
        # ...but a start the page actually prints still overrules the font,
        # in either direction, or the hint would be decoration.
        start, _ = fit_span(labels, hint="09:25")
        self.assertAlmostEqual(start / 60, hm("09:21") / 60, delta=1.0)
        start, _ = fit_span(labels, hint="03:30")
        self.assertAlmostEqual(start / 60, hm("03:21") / 60, delta=1.0)

    def test_the_majority_can_be_the_misread(self):
        # 01433 p188: five of eight labels read 13:xx — the line through the
        # 19s still wins because the 13s land on it on the right minute
        start, dur = fit_span([("18:50", 113), ("18:55", 200), ("13:00", 289), ("19:05", 376),
                               ("13:10", 465), ("13:15", 552), ("19:20", 641), ("19:25", 728)])
        self.assertAlmostEqual(start / 60, hm("18:47") / 60, delta=1.0)
        self.assertAlmostEqual(dur / 60, 42, delta=1.5)

    def test_a_clean_ladder_is_unchanged(self):
        # six labels 136 px apart: 5 min per 136 px, 732 px of plot
        start, dur = fit_span([("02:45", 100), ("02:50", 236), ("02:55", 372),
                               ("03:00", 508), ("03:05", 644), ("03:10", 780)])
        self.assertAlmostEqual(start, hm("02:45") - 41 * 300 / 136, delta=1.0)
        self.assertAlmostEqual(dur, 732 * 300 / 136, delta=1.0)

    def test_a_real_midnight_crossing_still_unwraps(self):
        start, dur = fit_span([("23:40", 100), ("23:50", 236), ("00:00", 372),
                               ("00:10", 508), ("00:20", 644), ("00:30", 780)])
        self.assertAlmostEqual(start, hm("23:40") - 41 * 600 / 136, delta=1.0)   # day 1, before midnight
        self.assertAlmostEqual(dur, 732 * 600 / 136, delta=1.0)

    def test_01350_p186_true_thirteens_are_not_rewritten(self):
        # 12:50 13:00 … 13:50 are the real labels; the page's printed Start
        # Time 02:41 is ten hours away and must not pull the ladder to 18:xx
        labels = [("12:50", 78), ("13:00", 195), ("13:10", 312), ("13:20", 430),
                  ("13:30", 547), ("13:40", 664), ("13:50", 782)]
        start, dur = fit_span(labels, hint="02:41")
        self.assertAlmostEqual(start / 60, hm("12:48") / 60, delta=1.0)
        self.assertAlmostEqual(dur / 60, 62.6, delta=1.0)
        # and the misread pages still resolve without any hint at all
        start, _ = fit_span([("18:50", 83), ("13:00", 172), ("13:10", 262), ("19:20", 352),
                             ("13:30", 441), ("19:40", 531), ("19:50", 620), ("20:00", 710)])
        self.assertAlmostEqual(start / 60, hm("18:47") / 60, delta=1.0)
        start, _ = fit_span([("09:25", 136), ("03:30", 244), ("03:35", 352), ("03:40", 462),
                             ("09:45", 569), ("03:50", 678), ("09:55", 785)])
        self.assertAlmostEqual(start / 60, hm("09:21") / 60, delta=1.0)

    def test_p155_is_a_long_window_not_a_misread(self):
        start, dur = fit_span([("02:00", 244), ("04:00", 352), ("06:00", 460), ("08:00", 570),
                               ("10:00", 678), ("12:00", 787)])
        self.assertAlmostEqual(dur / 3600, 13.5, delta=0.2)        # the crop's job, not the fit's


def window(n_s, t0_s, start, elapsed_s, plot=(59, 100, 791, 400)):
    samples = np.arange(n_s, dtype=float)
    chans = [{"key": "press", "values": samples.copy()}]        # value == original second
    info = {"plot": plot, "t0_seconds": float(t0_s), "duration_s": int(n_s), "notes": []}
    meta = {"start_time": start, "elapsed_s": elapsed_s}
    return tc._crop_to_printed_window(meta, samples, chans, info)


class PrintedWindow(unittest.TestCase):

    def test_p155_one_hour_stage_in_a_thirteen_hour_window(self):
        s, c, info, meta = window(48600, 0, "11:05:00", 3602)
        self.assertEqual(int(s[0]), 0)
        self.assertEqual(int(c[0]["values"][0]), 11 * 3600 + 300)   # sample 0 is 11:05
        self.assertEqual(info["duration_s"], 3662)                  # elapsed + a minute
        self.assertEqual(info["t0_seconds"], 39900.0)
        self.assertLess(info["duration_s"], tc.STAGE_MAX_S)
        self.assertAlmostEqual(info["plot"][0], 59 + 39900 * (732 / 48600), places=6)
        self.assertEqual(meta["start_time"], "11:05:00")
        self.assertIn("trimmed", info["notes"][-1])

    def test_p213_two_hour_window_around_stage_60(self):
        s, c, info, meta = window(8100, hm("04:30"), "06:03:00", 2054)
        self.assertEqual(info["duration_s"], 2114)
        self.assertEqual(int(c[0]["values"][0]), (hm("06:03") - hm("04:30")))

    def test_a_window_that_is_the_stage_is_left_alone(self):
        s, c, info, meta = window(2200, hm("08:05"), "08:04:00", 2208)
        self.assertEqual(info["duration_s"], 2200)
        self.assertEqual(info.get("notes"), [])

    def test_01350_p186_printed_start_outside_the_axis_is_left_whole(self):
        # Start Time 02:41 under a chart whose axis runs 12:50-13:58
        s, c, info, meta = window(4132, hm("12:50"), "02:41:00", 6538)
        self.assertEqual(info["duration_s"], 4132)
        self.assertEqual(len(c[0]["values"]), 4132)
        # and a printed start outside a window that IS wider than the stage
        s, c, info, meta = window(48600, hm("12:50"), "02:41:00", 3600)
        self.assertEqual(info["duration_s"], 48600)
        self.assertIn("outside", info["notes"][-1])

    def test_no_elapsed_printed_means_no_crop(self):
        samples = np.arange(48600, dtype=float)
        s, c, info, meta = tc._crop_to_printed_window(
            {"start_time": "11:05:00"}, samples, [{"values": samples}],
            {"plot": (59, 100, 791, 400), "t0_seconds": 0.0, "duration_s": 48600})
        self.assertEqual(info["duration_s"], 48600)


if __name__ == "__main__":
    unittest.main()
