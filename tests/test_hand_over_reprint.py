"""A chart printed twice under two numbers is not a hand-over (Canyon 00230).

_hand_over_tails cuts chart A where chart B begins when B re-plots A's last
minutes with the same values: a continuation. On 00230, p68 is interval 21
(9:15-9:57, 42 min of pumping) and p70 is labelled interval 22 but is the
SAME chart re-plotted a minute later — axis 9:16-9:58, identical curves.
Interval 22's own chart is not in the PDF. The pass saw "same values", cut
stage 21 to 62 samples ("last 39.5 min not exported here") and left the data
under 22.

A continuation re-plots a few minutes of A's tail: 782 of the 785 cuts in
00184-00278 hand over less than three quarters of A, 602 of them under a
tenth. A B that covers nearly all of A is a reprint, so A is kept whole, B
stays as printed, and B says what it is.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402


# One job-long signal both charts are cut from, so where they overlap they
# carry the same values — the evidence _lag_scores looks for.
_T = np.arange(40000, dtype=float)
_SIGNAL = 40.0 + 12.0 * np.sin(_T / 600.0) + 3.0 * np.sin(_T / 37.0)


def series(stage, start, n, at=0, src="Canyon chart"):
    """`n` seconds of the job signal from offset `at`, clocked at `start`."""
    return {"type": "series", "source": src, "page": 1,
            "meta": {"stage": stage, "date": "2017-08-10", "start_time": start,
                     "sample_sec": 1.0, "warnings": []},
            "samples": np.arange(n, dtype=float),
            "data": {"Tr Press": _SIGNAL[at:at + n].copy(),
                     "Slurry Rate": 5.0 + _SIGNAL[at:at + n] / 10.0},
            "units": {}, "labels": {}, "scales": {}, "frames": {}, "deduced": {}}


class Reprint(unittest.TestCase):

    def setUp(self):
        # 00230: interval 21 at 09:15:09 for 40.5 min, and "interval 22" the
        # same minutes re-plotted from 62 s in
        self.a = series("21", "09:15:09", 2432, at=0)
        self.b = series("22", "09:16:11", 2397, at=62)

    def test_the_first_chart_keeps_its_minutes(self):
        pipeline._hand_over_tails([self.a, self.b], [])
        self.assertEqual(len(self.a["samples"]), 2432,
                         "stage 21 was cut to hand its data to its own reprint")
        self.assertNotIn("handover", self.a)
        self.assertFalse(any("not exported here" in w
                             for w in self.a["meta"]["warnings"]))

    def test_the_reprint_stays_as_printed_and_says_so(self):
        notes = []
        pipeline._hand_over_tails([self.a, self.b], notes)
        self.assertEqual(len(self.b["samples"]), 2397)
        self.assertEqual(self.b["meta"]["start_time"], "09:16:11")
        ws = " ".join(self.b["meta"]["warnings"])
        self.assertIn("re-plots stage 21's chart", ws)
        self.assertIn("printed that chart twice", ws)
        self.assertTrue(any("printed one chart twice" in n and "21→22" in n
                            for n in notes), notes)

    def test_a_long_real_hand_over_is_still_cut(self):
        # B re-plots the last 70% of A — more than any real tail in the
        # corpus but short of a reprint — and A is still cut where B begins
        a = series("21", "09:00:00", 3000, at=0)
        b = series("22", "09:15:00", 3000, at=900)
        pipeline._hand_over_tails([a, b], [])
        self.assertEqual(len(a["samples"]), 900)
        self.assertFalse(any("printed that chart twice" in w
                             for w in b["meta"]["warnings"]))

    def test_the_same_number_twice_is_still_refused_on_the_first(self):
        # two charts of ONE stage keep the older refusal and its wording
        # (00028, #654): the reprint rule is for two numbers
        b = series("21", "09:16:11", 2397, at=62)
        pipeline._hand_over_tails([self.a, b], [])
        self.assertEqual(len(self.a["samples"]), 2432)
        self.assertTrue(any("cannot re-plot itself" in w
                            for w in self.a["meta"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
