"""A stage must not be cut before it stops pumping.

_hand_over_tails assumes chart A runs on PAST the next stage's start, and
cuts A where B's window opens. On Trican it is the other way round: chart B
opens ~11 min BEFORE stage B starts and re-plots the END of stage A as its
own lead-in. Both arrangements correlate identically over the overlap — they
are the same samples — so the correlation cannot tell them apart.

The data can. Measured on 00218, all 27 trimmed stages, BEFORE the fix: the
handed-over region began at exactly the proppant concentration the stage was
cut at (143, 243, 294, 344 kg/m3 …) and fell to 0, pressure ~60 -> ~27 MPa,
rate to 2. Stage 1 was cut at 96.0 min in the middle of 142 kg/m3 slurry; it
flushed to 101, pumped to 103 and shut down at 104.1, and all of that was
filed under stage 2. AFTER: 27 of 27 cut after the shutdown, none of them
mid-proppant, and stage 1 keeps 105.5 of its 107 printed minutes.

A stage never STARTS at 344 kg/m3 and ramps down to zero — so proppant at
the cut is the evidence, and without a proppant channel nothing is claimed
back.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline

SRC = "Trican treatment chart (raster)"


def stage(minutes, *, rate, conc, press=None):
    """One chart: rate/conc/press given as (value, minutes) runs."""
    def build(runs):
        out = []
        for v, m in runs:
            out.extend([float(v)] * int(m * 60))
        return np.asarray(out[:int(minutes * 60)], float)
    data = {"Slurry Rate": build(rate), "WH Prop Conc": build(conc)}
    data["Tr Press"] = build(press) if press else np.full(int(minutes * 60), 60.0)
    md = {"title": "Stage", "stage": "1", "date": "2020-01-24",
          "start_time": "23:46:00", "duration_min": minutes, "warnings": []}
    return pipeline._series(md, np.arange(int(minutes * 60), dtype=float),
                            data, SRC, page=50)


class KeepsItsEnd(unittest.TestCase):

    def cut(self, a, off):
        return pipeline._still_pumping_after(a, off, 1.0)

    def test_a_cut_in_the_middle_of_proppant_is_carried_to_the_shutdown(self):
        # 00218 stage 1 in miniature: 96 min of slurry, flush, then shutdown
        a = stage(107, rate=[(8.4, 103), (2.0, 4)],
                  conc=[(142, 100), (0, 7)],
                  press=[(60, 103), (27, 4)])
        got = self.cut(a, 96 * 60)
        self.assertGreater(got, 96 * 60, "cut landed mid-proppant and stayed")
        self.assertGreaterEqual(got / 60.0, 103, "the shutdown must stay with it")
        self.assertLessEqual(got / 60.0, 107)

    def test_a_cut_after_the_flush_is_left_alone(self):
        a = stage(107, rate=[(8.4, 103), (2.0, 4)],
                  conc=[(142, 100), (0, 7)],
                  press=[(60, 103), (27, 4)])
        self.assertEqual(self.cut(a, 105 * 60), 105 * 60)

    def test_a_chart_that_really_does_run_into_the_next_stage_is_left_alone(self):
        # A ends at 60, B starts at 62 with PAD — zero proppant, ramping up.
        # This is the arrangement the trim was written for and must not change.
        a = stage(80, rate=[(8.4, 58), (0, 4), (8.0, 18)],
                  conc=[(300, 55), (0, 10), (50, 15)],
                  press=[(60, 58), (25, 4), (55, 18)])
        self.assertEqual(self.cut(a, 62 * 60), 62 * 60)

    def test_without_a_proppant_channel_nothing_is_claimed_back(self):
        a = stage(107, rate=[(8.4, 103), (2.0, 4)], conc=[(0, 107)])
        self.assertEqual(self.cut(a, 96 * 60), 96 * 60)

    def test_a_stage_that_never_stops_is_not_extended_past_its_own_end(self):
        a = stage(60, rate=[(8.4, 60)], conc=[(300, 60)])
        self.assertLessEqual(self.cut(a, 50 * 60), 60 * 60)

    def test_a_cut_at_the_very_end_cannot_run_off_the_chart(self):
        a = stage(60, rate=[(8.4, 60)], conc=[(300, 60)])
        self.assertLessEqual(self.cut(a, 60 * 60 - 1), 60 * 60)


class EndToEnd(unittest.TestCase):
    """Through _hand_over_tails itself, not just the helper."""

    def pair(self):
        a = stage(107, rate=[(8.4, 103), (2.0, 4)],
                  conc=[(142, 100), (0, 7)],
                  press=[(60, 103), (27, 4)])
        a["meta"]["clock_chart"] = True
        # B opens at A's minute 96 and re-plots A's last 11 minutes
        b = stage(61, rate=[(8.4, 7), (2.0, 4), (8.4, 50)],
                  conc=[(142, 4), (0, 57)],
                  press=[(60, 7), (27, 4), (60, 50)])
        b["meta"].update({"stage": "2", "start_time": "01:22:00",
                          "date": "2020-01-25", "clock_chart": True})
        b["page"] = 52
        return a, b

    def test_the_stage_keeps_its_flush_and_its_shutdown(self):
        a, b = self.pair()
        pipeline._hand_over_tails([a, b], [])
        kept = len(a["samples"]) / 60.0
        self.assertGreaterEqual(kept, 103, f"cut at {kept:.1f} min, before the shutdown")
        self.assertLessEqual(kept, 107)
        self.assertTrue(any("before this stage ends" in w
                            for w in a["meta"]["warnings"]),
                        "moving the cut has to be said out loud")


if __name__ == "__main__":
    unittest.main()
