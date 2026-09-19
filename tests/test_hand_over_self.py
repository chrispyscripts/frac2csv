"""A stage cannot hand its data to itself.

_hand_over_tails walks charts in time order within a source group and cuts one
where the next begins, so the same minutes are not exported twice. It names the
handover after the next chart's stage — and never checked that the next chart
is a DIFFERENT stage.

On 00028 the report prints stage 7 on two pages. The first was cut to 61
samples with "the chart runs on into stage 7, whose own chart re-plots those
minutes", and the chart it meant was the other stage 7. The export then held a
one-minute stub and a near-complete chart, both labelled 7, and the stub is the
one that surfaced: Carmine reported it as "not picking up stage 7" (#654), and
stage 29 went the same way (#657). 258 minutes of that file were being deleted.

The recovered stage 7 reads 205.7 min, and its chemical chart on the same page
independently reads 205.97 — two charts of one stage agreeing, which is the
check that says this is right rather than merely different.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402


# One job-long signal both charts are cut from, so where they overlap they
# carry the SAME values — which is the evidence _lag_scores looks for. A flat
# trace correlates with nothing and no handover is offered at all, which made
# the first version of this file pass without the guard even being reached.
_T = np.arange(40000, dtype=float)
_SIGNAL = 40.0 + 12.0 * np.sin(_T / 600.0) + 3.0 * np.sin(_T / 37.0)


def series(stage, start, n, at=0, src="chart"):
    """`n` seconds of the job signal from offset `at`, filed at `start`."""
    return {"type": "series", "source": src, "page": 1,
            "meta": {"stage": stage, "date": "2018-07-08", "start_time": start,
                     "sample_sec": 1.0},
            "samples": np.arange(n, dtype=float),
            "data": {"Tr Press": _SIGNAL[at:at + n].copy()},
            "units": {}, "labels": {}, "scales": {}, "frames": {}, "deduced": {}}


def trimmed_len(r):
    return len(r["samples"])


class HandOverSelf(unittest.TestCase):
    def test_two_charts_of_the_same_stage_are_not_trimmed(self):
        # the 00028 shape: a long chart, then a second chart of the SAME stage
        # starting a minute in
        a = series("7", "08:40:00", 12000, at=0)
        b = series("7", "08:50:00", 11400, at=600)
        pipeline._hand_over_tails([a, b], [])
        self.assertEqual(trimmed_len(a), 12000,
                         "a stage was cut to hand its data to itself")

    def test_the_refusal_says_why(self):
        a = series("7", "08:40:00", 12000, at=0)
        b = series("7", "08:50:00", 11400, at=600)
        pipeline._hand_over_tails([a, b], [])
        ws = " ".join(a["meta"].get("warnings") or [])
        self.assertIn("cannot re-plot itself", ws)

    def test_a_genuine_handover_still_happens(self):
        # different stages: this is the behaviour #645 asked for, untouched
        a = series("7", "08:40:00", 12000, at=0)
        b = series("8", "08:50:00", 11400, at=600)
        pipeline._hand_over_tails([a, b], [])
        self.assertLess(trimmed_len(a), 12000,
                        "a real handover between two stages stopped working")

    def test_unlabelled_charts_are_not_refused(self):
        # two charts with no stage number are not evidence of anything, and
        # refusing them would suppress real handovers on files that print none
        a = series("", "08:40:00", 12000, at=0)
        b = series("", "08:50:00", 11400, at=600)
        pipeline._hand_over_tails([a, b], [])
        self.assertLess(trimmed_len(a), 12000)

    def test_labels_compare_as_text(self):
        # "7" and 7 are the same stage however the reader typed it
        a = series(7, "08:40:00", 12000, at=0)
        b = series("7", "08:50:00", 11400, at=600)
        pipeline._hand_over_tails([a, b], [])
        self.assertEqual(trimmed_len(a), 12000)


if __name__ == "__main__":
    unittest.main()
