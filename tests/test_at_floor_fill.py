"""A pen resting on the axis floor is a reading of zero, not a hole.

Where a rate sits shut in, its trace coincides with the frame's bottom rule,
the tracer finds no ink, and the channel came out blank — while the chart drew
a line along the floor. 00218 stage 1: Slurry Rate 46% empty, longest run
33.7 min, decaying to 0.089 m3/min going in and resuming at 0.107 coming out
on a 0..12.5 axis. It did not go anywhere; it was off. Read into another
program those blanks look exactly like data loss.

gaps.py has separated a resting pen from a lost trace since it was written.
Only AT_FLOOR is filled, and only with an axis to measure the floor against.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gaps


class AtFloor(unittest.TestCase):

    def runs(self, vals, axis=(0.0, 12.5)):
        return gaps.find_gaps(vals, axis)

    def test_a_rate_shut_in_is_classified_at_floor(self):
        v = [8.0] * 10 + [0.09] + [None] * 40 + [0.11] + [8.0] * 10
        g = self.runs(v)
        self.assertEqual([x["kind"] for x in g], [gaps.AT_FLOOR])

    def test_and_is_filled_with_the_floor_it_rested_on(self):
        v = [8.0] * 10 + [0.09] + [None] * 40 + [0.11] + [8.0] * 10
        out, filled = gaps.interpolate(v, self.runs(v), kinds=(gaps.AT_FLOOR,))
        self.assertEqual(len(filled), 40)
        self.assertTrue(all(x is not None for x in out))
        # between the two ends it rested on, never up at pumping rate
        self.assertTrue(all(0.08 <= out[i] <= 0.12 for i in filled), out[11:14])

    def test_a_gap_mid_flight_is_NOT_filled(self):
        # both ends well off the floor: something was lost, and inventing a
        # rate across it would be inventing a treatment
        v = [8.0] * 10 + [8.1] + [None] * 40 + [8.2] + [8.0] * 10
        g = self.runs(v)
        self.assertEqual([x["kind"] for x in g], [gaps.MISSING])
        out, filled = gaps.interpolate(v, g, kinds=(gaps.AT_FLOOR,))
        self.assertEqual(filled, [])
        self.assertIsNone(out[20])

    def test_one_end_off_the_floor_is_not_a_rest(self):
        v = [8.0] * 10 + [0.09] + [None] * 40 + [8.2] + [8.0] * 10
        self.assertEqual([x["kind"] for x in self.runs(v)], [gaps.MISSING])

    def test_without_an_axis_nothing_is_claimed(self):
        v = [8.0] * 10 + [0.09] + [None] * 40 + [0.11] + [8.0] * 10
        g = gaps.find_gaps(v, None)
        self.assertEqual([x["kind"] for x in g], [gaps.UNKNOWN])
        _out, filled = gaps.interpolate(v, g, kinds=(gaps.AT_FLOOR,))
        self.assertEqual(filled, [])

    def test_lead_and_trail_stay_empty(self):
        # before the pen starts and after the flush there is nothing to say
        v = [None] * 5 + [8.0] * 10 + [None] * 5
        g = self.runs(v)
        self.assertEqual({x["kind"] for x in g}, {gaps.LEAD, gaps.TRAIL})
        out, filled = gaps.interpolate(v, g, kinds=(gaps.AT_FLOOR,))
        self.assertEqual(filled, [])
        self.assertIsNone(out[0])
        self.assertIsNone(out[-1])


if __name__ == "__main__":
    unittest.main()
