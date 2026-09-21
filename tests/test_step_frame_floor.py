"""The plot's bottom rule is found even when it is anti-aliased into grey.

_frame_bbox took the lowest row that is >60% strict-black (sum < 400). That
is the frame on most pages and the wrong line wherever the bottom rule is
about 1.5 px tall, because it then renders as two PALE rows while an interior
gridline landing on one row renders darker than either. On 00344's surface
chart:

    row 321, a gridline          (103,103,103)  sum 309   dark
    row 426, the frame's bottom  (170,170,170)  sum 510   not dark
    row 427, the rest of it      (143,143,143)  sum 429   not dark

The box ended at the gridline, the clock strip was then read from a band
INSIDE the plot, and all 32 surface charts died with "time axis unreadable" —
the file exported chemical traces and none of the four channels anyone wants
(#693). The chemical chart on the same page renders its floor crisply and
read fine, which is why the file looked half-alive rather than broken.

The side rules are vertical, so half a pixel of width darkens one column
instead of splitting across two.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import step1

W, H = 400, 300
TOP, BOT, LEFT, RIGHT = 10, 250, 20, 380


def chart(soft_floor=False, title_below=False):
    """A white plot with a black frame and one interior gridline.

    `soft_floor` renders the bottom rule the way the real page does: split
    across two rows, each too pale to pass the strict-dark test, with the
    side rules still solid down to the lower of them.
    """
    img = np.full((H, W, 3), 255, int)
    img[TOP, LEFT:RIGHT] = 0                 # top rule
    img[150, LEFT:RIGHT] = 103               # an interior gridline: DARK
    if soft_floor:
        img[BOT - 1, LEFT:RIGHT] = 170       # sum 510 — not dark
        img[BOT, LEFT:RIGHT] = 143           # sum 429 — not dark
    else:
        img[BOT, LEFT:RIGHT] = 0
    img[TOP:BOT + 1, LEFT] = 0               # left rule, solid to the floor
    img[TOP:BOT + 1, RIGHT] = 0              # right rule
    if title_below:
        # the rotated axis title, in the same column as the left rule
        img[BOT + 40:BOT + 80, LEFT] = 0
    return img


class FrameFloor(unittest.TestCase):

    def test_a_clear_floor_is_found_as_it_always_was(self):
        self.assertEqual(step1._frame_bbox(chart())[3], BOT)

    def test_a_soft_floor_is_still_the_floor(self):
        box = step1._frame_bbox(chart(soft_floor=True))
        self.assertEqual(box[3], BOT,
                         "took the gridline, so the clock strip is read "
                         "inside the plot and the chart dies")

    def test_the_gridline_is_not_mistaken_for_it(self):
        self.assertNotEqual(step1._frame_bbox(chart(soft_floor=True))[3], 150)

    def test_the_axis_title_below_the_frame_is_not_swallowed(self):
        # a plain min/max down the left column would run to the title
        box = step1._frame_bbox(chart(soft_floor=True, title_below=True))
        self.assertEqual(box[3], BOT)

    def test_the_sides_and_top_are_unchanged(self):
        box = step1._frame_bbox(chart(soft_floor=True))
        self.assertEqual((box[0], box[1], box[2]), (LEFT, TOP, RIGHT))

    def test_a_blank_image_still_returns_none(self):
        self.assertIsNone(step1._frame_bbox(np.full((H, W, 3), 255, int)))


if __name__ == "__main__":
    unittest.main()
