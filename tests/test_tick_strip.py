"""Time-axis tick ladders read off a SIDEWAYS strip, and what they fit to.

The MView portrait sheets print the time axis rotated — "0 5 10 15 20 25"
running bottom-to-top beside the plot — and the full-page OCR pass reads
those digits unevenly: 8 of 8 on page 61 of 00339, 2 of 6 on page 238. Two
ticks do not fit a line, so page 238's stage was thrown away with "stage
duration unknown", and 97 of that file's chart pages went the same way. That
is more than three times every other cause put together, and the whole of why
eight filings yielded 295 charts against 563 printed zones.

ocr_labels never retried rotated on its own because of _UPRIGHT_ENOUGH: these
pages read plenty of OTHER numbers upright.

The ladders below are the real readings, measured off the pages. They are
here so the fit that turns them into a duration cannot drift.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import frac_core as fc                                   # noqa: E402


class TickLadders(unittest.TestCase):
    """(page position, minutes) as the rotated strip reads them."""

    def test_p238_recovers_a_stage_that_was_thrown_away(self):
        pts = [(194.8, 20.0), (336.0, 15.0), (477.8, 10.0),
               (619.6, 5.0), (761.4, 0.0)]
        self.assertEqual(fc._fit_time_axis(pts, 53.33), 25)

    def test_p61_agrees_with_what_the_page_pass_already_got_right(self):
        pts = [(141.6, 35.0), (230.1, 30.0), (318.7, 25.0), (407.2, 20.0),
               (495.5, 15.0), (584.2, 10.0), (672.8, 5.0), (761.4, 0.0)]
        self.assertEqual(fc._fit_time_axis(pts, 53.33), 40)

    def test_p86_the_same(self):
        pts = [(173.2, 100.0), (290.9, 80.0), (408.5, 60.0),
               (526.0, 40.0), (643.6, 20.0)]
        self.assertEqual(fc._fit_time_axis(pts, 56.0), 120)

    def test_three_ticks_are_still_refused(self):
        # p258. Evenly spaced and almost certainly 15 minutes, but three
        # points leave nothing spare to catch a misread digit, so the
        # >=4 guard stands and the page stays a visible gap.
        pts = [(289.8, 10.0), (525.6, 5.0), (761.2, 0.0)]
        self.assertIsNone(fc._fit_time_axis(pts, 54.0))

    def test_a_stray_from_a_neighbouring_axis_is_thrown_out(self):
        # every one of these pages carries a "100" at x=610, off the time
        # column entirely — it is a value axis's label sitting in the band
        pts = [(53.0, 40.0), (141.0, 35.0), (230.0, 30.0), (318.0, 25.0),
               (495.0, 15.0), (584.0, 10.0), (652.0, 100.0)]
        self.assertEqual(fc._fit_time_axis(pts, 53.0), 40)

    def test_a_ladder_that_is_not_a_ladder(self):
        self.assertIsNone(fc._fit_time_axis(
            [(100.0, 5.0), (200.0, 900.0), (300.0, 7.0), (400.0, 3.0)], 50.0))


class StripGuards(unittest.TestCase):
    def test_a_half_turn_is_refused(self):
        # 180 degrees leaves the digits sideways; only an odd turn stands
        # them up, and asking for an even one is a caller mistake
        class _P(object):
            rect = None
        self.assertEqual(
            fc.ocr_labels.rotated_tick_column(_P(), None, turn=2), [])


if __name__ == "__main__":
    unittest.main()
