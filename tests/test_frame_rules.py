"""A STEP chart frame whose side rules are printed broken.

00269 p37's offset chart draws its left rule barely darker than the frame
finder's cut-off, in pieces a pixel or a few apart — 302-421, 428-549,
550-669, 670-908 — and no piece reached the 10%-of-page minimum alone. The
box came back as the bottom 238 px of a 606 px frame, and every offset well
above the lower third read blank (00269-00274, v1.11.49's release notes).

  python3 -m unittest tests.test_frame_rules
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import step1                                             # noqa: E402

H, W = 2414, 1866


# 00269 p37's four rule columns, piece by piece, as the page prints them
P37 = {158: [(302, 421), (428, 549), (550, 669), (670, 908)],
       159: [(302, 420), (429, 666), (677, 908)],
       1690: [(302, 458), (466, 668), (669, 919)],
       1691: [(302, 425), (428, 459), (466, 666), (681, 909)]}


def page(cols):
    """A white page with one chart frame, its side rules drawn in the pieces
    `cols` {x: [(y0, y1)]}, and its top and bottom rules whole."""
    img = np.full((H, W, 3), 255, np.uint8)
    for x, pieces in cols.items():
        for a, b in pieces:
            img[a:b, x] = 82                             # sum 246, as printed
    img[302:304, 158:1692] = 82
    img[906:908, 158:1692] = 82
    return img


class BrokenRule(unittest.TestCase):
    def test_a_rule_broken_a_few_pixels_apart_is_one_rule(self):
        boxes = step1.find_charts(page(P37))
        self.assertEqual(len(boxes), 1)
        x0, y0, x1, y1 = boxes[0]
        self.assertLessEqual(y0, 302)
        self.assertGreaterEqual(y1, 906)

    def test_two_charts_far_apart_stay_two(self):
        img = page({x: [(302, 908)] for x in (158, 159, 1690, 1691)})
        img[1362:2062, [158, 159, 1690, 1691]] = 82
        self.assertEqual(len(step1.find_charts(img)), 2)

    def test_a_whole_frame_is_not_moved(self):
        img = page({x: [(302, 908)] for x in (158, 159, 1690, 1691)})
        img[1000:1012, 1600] = 82                       # a tick below it
        self.assertEqual(step1.find_charts(img), [(158, 302, 1691, 908)])


class Runs(unittest.TestCase):
    def test_without_a_gap_a_break_ends_the_run(self):
        col = np.zeros(40, bool)
        col[2:12] = True
        col[14:30] = True
        self.assertEqual(step1._runs(col, 5), [(2, 12), (14, 30)])

    def test_a_break_within_the_gap_is_bridged(self):
        col = np.zeros(40, bool)
        col[2:12] = True
        col[14:30] = True
        self.assertEqual(step1._runs(col, 5, gap=2, trim=5), [(2, 30)])
        self.assertEqual(step1._runs(col, 5, gap=1, trim=5), [(2, 12), (14, 30)])

    def test_a_short_piece_at_the_end_is_not_bridged_on(self):
        # 00184: a frame rule ending at 1003, a tick mark a few px below it
        col = np.zeros(1100, bool)
        col[332:1003] = True
        col[1008:1020] = True
        self.assertEqual(step1._runs(col, 200, gap=8), [(332, 1003)])

    def test_a_short_end_piece_a_pixel_off_is_the_rule(self):
        # 00243 p82: the rule runs on to its floor after a 1 px break
        col = np.zeros(1100, bool)
        col[340:997] = True
        col[998:1025] = True
        self.assertEqual(step1._runs(col, 200, gap=8), [(340, 1025)])

    def test_a_run_to_the_end_of_the_column(self):
        col = np.zeros(20, bool)
        col[10:] = True
        self.assertEqual(step1._runs(col, 5, gap=3, trim=5), [(10, 20)])


class FlattenedPlotBox(unittest.TestCase):
    """00935 p47 (#810, stage 6): a 2024 chart flattened into pictures. The
    plot's top rule falls across a pixel boundary and is anti-aliased over two
    rows at (154,154,154) and (157,157,157) — a sum of 462 against the 450
    the side rules are found at — so the plot had no box, and the page was
    read by the tiled reader as a casing chart and dropped."""

    def page(self, top=((572, 154), (573, 157))):
        img = np.full((2550, 3300, 3), 255, np.uint8)
        img[262:266, 177:3143] = (120, 60, 30)           # the brown panel
        img[2395:2399, 177:3143] = (120, 60, 30)
        img[262:2399, 177:181] = (120, 60, 30)
        img[262:2399, 3139:3143] = (120, 60, 30)
        img[573:1736, 382:385] = 96                      # the plot's sides
        img[573:1736, 2700:2703] = 96
        img[1733:1736, 382:2703] = 96                    # and its floor
        for y, v in top:
            img[y, 382:2703] = v
        return img

    def test_an_anti_aliased_top_rule_still_closes_the_plot(self):
        box = step1._inner_plot_box(self.page())
        self.assertIsNotNone(box)
        x0, y0, x1, y1 = box
        self.assertLess(abs(x0 - 382), 4)
        self.assertLess(abs(y0 - 573), 4)
        self.assertLess(abs(y1 - 1736), 4)

    def test_no_top_rule_no_plot(self):
        box = step1._inner_plot_box(self.page(top=()))
        self.assertTrue(box is None or box[0] < 200)     # only the panel


if __name__ == "__main__":
    unittest.main()
