"""STEP's 2019 tiled pages: the whole page as image stripes, with a logo and
hairline rules among them (00180-1021).

  python3 -m unittest tests.test_step_tiled
"""
import os
import sys
import unittest

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import step1                                             # noqa: E402


class _Page(object):
    def __init__(self, rects, width=612.0, height=792.0):
        self.rect = fitz.Rect(0, 0, width, height)
        self._rects = rects
        self.rotation = 0

    def get_images(self, full=True):
        return [(i, 0, 1101, 79, 8, "DeviceRGB", "", f"im{i}", "", 0) for i in range(len(self._rects))]

    def get_image_rects(self, xref):
        return [fitz.Rect(*self._rects[xref])]


class DetectTiled(unittest.TestCase):

    def test_full_width_stripes_are_tiles(self):
        page = _Page([(25, 94 + 25 * i, 585, 119 + 25 * i) for i in range(20)])
        self.assertTrue(step1._detect_tiled(page))

    def test_a_logo_and_two_rules_among_the_stripes_do_not_break_it(self):
        stripes = [(25, 94 + 25 * i, 585, 119 + 25 * i) for i in range(20)]
        junk = [(18, 763, 120, 770), (49, 769, 51, 769), (55, 769, 56, 769)]
        self.assertTrue(step1._detect_tiled(_Page(stripes + junk)))

    def test_two_different_stripe_widths_are_not_one_tiling(self):
        stripes = [(25, 94 + 25 * i, 585, 119 + 25 * i) for i in range(10)]
        others = [(25, 400 + 25 * i, 480, 425 + 25 * i) for i in range(10)]
        self.assertFalse(step1._detect_tiled(_Page(stripes + others)))

    def test_fewer_than_three_stripes_is_no_tiling(self):
        self.assertFalse(step1._detect_tiled(_Page([(25, 94, 585, 119), (25, 119, 585, 144)])))


if __name__ == "__main__":
    unittest.main()
