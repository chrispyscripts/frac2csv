"""Gap classification and interpolation.

Every case here is a shape the corpus actually produced, because the danger
in this area is not a wrong number — it is a plausible one. Three attempts at
filling gaps have been backed out of this project; these tests encode why.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gaps                                              # noqa: E402

RATE = (0.0, 20.0)


class FindGaps(unittest.TestCase):
    def test_no_gap(self):
        self.assertEqual(gaps.find_gaps([1.0, 2.0, 3.0], RATE), [])

    def test_lead_and_trail_are_not_losses(self):
        # Trican: 84% of 8,148 blank columns sit before the first reading or
        # after the last. That is the pad and the flush, and resample is right
        # to hand back nothing.
        g = gaps.find_gaps([None, None, 5.0, 6.0, None, None], RATE)
        self.assertEqual([x["kind"] for x in g], [gaps.LEAD, gaps.TRAIL])

    def test_resting_at_zero_is_the_pen_lifting(self):
        # 00183: the chart lifts its pen while the pumps are off. The gap holds
        # no ink at all. Filling it would invent a rate for a well not pumping.
        g = gaps.find_gaps([0.0, 0.1, None, None, 0.05, 0.0], RATE)
        self.assertEqual([x["kind"] for x in g], [gaps.AT_FLOOR])

    def test_mid_flight_both_sides_is_missing(self):
        g = gaps.find_gaps([12.0, 12.5, None, None, 13.0, 13.2], RATE)
        self.assertEqual([x["kind"] for x in g], [gaps.MISSING])
        self.assertEqual((g[0]["start"], g[0]["end"], g[0]["n"]), (2, 3, 2))
        self.assertEqual((g[0]["before"], g[0]["after"]), (12.5, 13.0))

    def test_pinned_at_full_scale_is_not_missing(self):
        g = gaps.find_gaps([19.9, 20.0, None, 20.0, 19.8], RATE)
        self.assertEqual([x["kind"] for x in g], [gaps.AT_CEIL])

    def test_one_side_resting_one_side_flying_is_missing(self):
        # The proppant ramp's step risers in #112: the curve leaves at one
        # level and returns at another. Something WAS lost here.
        g = gaps.find_gaps([0.0, 0.1, None, None, 9.0, 9.4], RATE)
        self.assertEqual([x["kind"] for x in g], [gaps.MISSING])

    def test_without_an_axis_nothing_is_called_missing(self):
        # "off the floor" has no meaning without a floor. A channel whose axis
        # could not be read must not have its gaps filled on a guess.
        g = gaps.find_gaps([12.0, None, 13.0], None)
        self.assertNotEqual(g[0]["kind"], gaps.MISSING)

    def test_tolerance_near_zero(self):
        # A curve drawn AT zero reads a little above it: the pen has width and
        # the frame line is painted over the bottom row. An exact test would
        # call this mid-flight and fill it.
        g = gaps.find_gaps([0.3, 0.2, None, 0.25, 0.3], RATE)
        self.assertEqual([x["kind"] for x in g], [gaps.AT_FLOOR])


class Interpolate(unittest.TestCase):
    def test_fills_only_missing_and_reports_what_it_filled(self):
        v = [10.0, None, None, 13.0]
        g = gaps.find_gaps(v, RATE)
        out, filled = gaps.interpolate(v, g)
        self.assertEqual(filled, [1, 2])
        self.assertAlmostEqual(out[1], 11.0)
        self.assertAlmostEqual(out[2], 12.0)

    def test_leaves_resting_gaps_alone(self):
        v = [0.0, None, None, 0.0]
        out, filled = gaps.interpolate(v, gaps.find_gaps(v, RATE))
        self.assertEqual(filled, [])
        self.assertEqual(out, v)

    def test_never_extrapolates_past_the_ends(self):
        v = [None, 5.0, 6.0, None]
        out, filled = gaps.interpolate(v, gaps.find_gaps(v, RATE),
                                       kinds=(gaps.LEAD, gaps.TRAIL,
                                              gaps.MISSING))
        self.assertEqual(filled, [])         # no value on one side to fill from
        self.assertEqual(out, v)

    def test_the_original_is_not_mutated(self):
        v = [10.0, None, 12.0]
        out, _ = gaps.interpolate(v, gaps.find_gaps(v, RATE))
        self.assertIsNone(v[1])
        self.assertIsNotNone(out[1])


class Note(unittest.TestCase):
    def test_says_missing_and_at_rest_separately(self):
        # The client's question is always "is this a hole in your reader or a
        # hole in the job". One number cannot answer it.
        v = [12.0] + [None] * 60 + [12.0] + [0.0] + [None] * 120 + [0.0]
        n = gaps.note("Slurry Rate", gaps.find_gaps(v, RATE))
        self.assertIn("data is missing", n)
        self.assertIn("at rest", n)
        self.assertIn("1.0 min", n)          # 60 samples at 1 s
        self.assertIn("2.0 min", n)          # 120 samples

    def test_silent_when_there_is_nothing_to_say(self):
        self.assertEqual(gaps.note("Tr Press", gaps.find_gaps([1.0, 2.0], RATE)), "")


if __name__ == "__main__":
    unittest.main()
