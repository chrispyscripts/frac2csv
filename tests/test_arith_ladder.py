"""The three-label tick ladder, and what must not pass for one.

  python3 -m unittest tests.test_arith_ladder

Four labels was the price of not trusting OCR, and it was being paid in whole
channels: 00915 p108 prints a rate axis, OCR reads three of its labels
([12, 16, 20], evenly stepped and evenly spaced), the fit is refused and
Slurry Rate vanishes from the page with nothing to say it did. Twenty-two of
that file's twenty-four treatment charts lose it the same way.

The replacement asks for the evidence rather than for a count: values that
step evenly AND positions that step evenly. These tests are mostly about the
second half — a rule that only checked the values would accept three misreads
that happen to be arithmetic.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1


def pts(pairs):
    """(value, position) -> the (value, cx, cy) triples the fit works in."""
    return [(v, x, 0.0) for v, x in pairs]


class ArithLadder(unittest.TestCase):
    def test_the_real_00915_p108_rate_axis(self):
        # 12/16/20 down an evenly spaced column — an axis, plainly
        self.assertTrue(lib1._arith_ladder(pts([(12, 100), (16, 120), (20, 140)])))

    def test_descending_reads_the_same(self):
        # the ladder is sorted by position, so which end is which is not a fact
        # about the axis
        self.assertTrue(lib1._arith_ladder(pts([(20, 100), (16, 120), (12, 140)])))

    def test_even_values_but_uneven_positions_is_not_an_axis(self):
        # this is the case a values-only rule would wave through: the numbers
        # are arithmetic and the labels are nowhere near a common spacing
        self.assertFalse(lib1._arith_ladder(pts([(12, 100), (16, 104), (20, 140)])))

    def test_even_positions_but_uneven_values_is_not_an_axis(self):
        self.assertFalse(lib1._arith_ladder(pts([(3, 100), (17, 120), (20, 140)])))

    def test_values_that_turn_around_are_misreads(self):
        # 20, 16, 20 down the column: the middle one cannot be on this axis
        self.assertFalse(lib1._arith_ladder(pts([(20, 100), (16, 120), (20, 140)])))

    def test_two_labels_do_not_qualify(self):
        # two points DO determine a line; they carry no evidence that they are
        # a ladder rather than two unrelated numbers, which is the whole point
        self.assertFalse(lib1._arith_ladder(pts([(12, 100), (16, 120)])))

    def test_four_labels_are_not_this_rule_s_business(self):
        # four already pass the ordinary path; this must not claim them
        self.assertFalse(
            lib1._arith_ladder(pts([(12, 100), (16, 120), (20, 140), (24, 160)])))

    def test_repeated_value_is_refused(self):
        self.assertFalse(lib1._arith_ladder(pts([(16, 100), (16, 120), (16, 140)])))

    def test_labels_stacked_on_one_position_are_refused(self):
        self.assertFalse(lib1._arith_ladder(pts([(12, 100), (16, 100), (20, 100)])))

    def test_five_percent_of_slop_is_allowed(self):
        # real tick centroids are not exact — 300/600/900 on a scanned page
        # lands a fraction of a point off
        self.assertTrue(lib1._arith_ladder(pts([(300, 100), (600, 120), (900, 140.8)])))
        # and 20% is not slop, it is a different spacing
        self.assertFalse(lib1._arith_ladder(pts([(300, 100), (600, 120), (900, 144)])))


if __name__ == "__main__":
    unittest.main()
