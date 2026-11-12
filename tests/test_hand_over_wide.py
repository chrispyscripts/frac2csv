"""A chart does not hand its minutes to an earlier stage.

00272 p49 is filed as stage 15, an Offset Analysis that prints the whole day,
02:45-15:45: stages 7 to 15. Put on its own clock it sits before stage 7's
chart, re-plots it, and was cut where stage 7 opens. Stage 15 kept the first
2 h of the day and handed the other 10.9 h, its own minutes among them, to
stage 7. v1.11.54 did that once its Surface Pressure read right; before, the
10x-low pressure made the two charts disagree and nothing was cut. 00269 p85
(stage 29, 13:00-20:45) and 00242 p70 (stage 25's chemistry: 286 s kept of
2 h) were cut the same way.

A wide window like that is kept as printed. A backward pair that hands over a
few minutes is not touched (00197 p52 prints stage 15's window under stage 19,
and its last 5 min are stage 16's).

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_hand_over_self import series                   # noqa: E402

import pipeline                                          # noqa: E402


class HandOverWide(unittest.TestCase):
    def test_a_day_long_plot_is_not_cut_at_an_earlier_stage(self):
        # the 00272 p49 shape: stage 15's plot runs 10 000 s; stage 7's chart
        # opens 2 000 s in and carries the same values
        a = series("15", "02:45:00", 10000, at=0)
        b = series("7", "03:18:20", 3000, at=2000)
        notes = []
        pipeline._hand_over_tails([a, b], notes)
        self.assertEqual(len(a["samples"]), 10000,
                         "a day-long plot was cut where an earlier stage opens")
        self.assertIsNone(a.get("handover"),
                          "and its own stage's minutes went to the earlier stage")
        self.assertIn("wider plot than this stage",
                      " ".join(a["meta"].get("warnings") or []))
        self.assertTrue(any("wider window" in n for n in notes))

    def test_a_few_minutes_to_an_earlier_number_still_go(self):
        # the 00197 p52 shape: a chart filed under 19 that is stage 15's
        # window; the next chart, stage 16, re-plots its last ten minutes
        a = series("19", "08:40:00", 6000, at=0)
        b = series("16", "10:10:00", 4000, at=5400)
        pipeline._hand_over_tails([a, b], [])
        self.assertLess(len(a["samples"]), 6000)
        self.assertEqual((a.get("handover") or {}).get("to"), "16")

    def test_a_forward_handover_is_unchanged(self):
        a = series("7", "08:40:00", 6000, at=0)
        b = series("8", "10:10:00", 4000, at=5400)
        pipeline._hand_over_tails([a, b], [])
        self.assertLess(len(a["samples"]), 6000)
        self.assertEqual((a.get("handover") or {}).get("to"), "8")


if __name__ == "__main__":
    unittest.main()
