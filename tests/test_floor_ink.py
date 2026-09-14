"""The floor walk consults the page's ink, not only the cover's mask (01316 p195, #627).

  python3 -m unittest tests.test_floor_ink
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import curve_trace as ct                                   # noqa: E402

H, N = 200, 120           # floor_px = max(3, 0.02*200) = 4: rows 195..199 are "at the floor"
FLOOR = 197


def masks():
    """Orange visible from col 60 on at the floor then rising; green at the
    floor cols 30..55 and above it elsewhere; nothing of either in 0..29."""
    o = np.zeros((H, N), bool); po = np.full(N, np.nan)
    g = np.zeros((H, N), bool); pg = np.full(N, np.nan)
    for c in range(60, N):
        r = FLOOR - min(80, (c - 60) * 2)
        o[r:r + 2, c] = True; po[c] = r + 0.5
    for c in range(30, 56):
        g[FLOOR:FLOOR + 2, c] = True; pg[c] = FLOOR + 0.5
    for c in list(range(0, 30)) + list(range(56, N)):
        g[100:102, c] = True; pg[c] = 100.5
    return o, po, g, pg


class PadUnderOtherInk(unittest.TestCase):

    def test_without_ink_the_walk_stops_at_the_green_gap(self):
        o, po, g, pg = masks()
        got = ct.fill_under(o, po, g, pg, islands=False)
        # cols 56..59 have no cover at the floor: four dropouts, walk ends
        self.assertEqual(got, [])
        self.assertTrue(np.isnan(po[:60]).all())

    def test_khaki_and_blue_at_the_floor_carry_the_walk_to_the_left_edge(self):
        o, po, g, pg = masks()
        ink = o | g
        ink[FLOOR:FLOOR + 2, 56:60] = True        # the blend of two pens
        ink[FLOOR:FLOOR + 2, 0:30] = True         # another pen (blue) at the floor
        got = ct.fill_under(o, po, g, pg, islands=False, ink=ink)
        self.assertEqual(got, list(range(0, 60)))
        self.assertTrue(np.allclose(po[:60], FLOOR + 0.5))

    def test_a_gap_in_the_floor_ink_still_ends_the_walk(self):
        o, po, g, pg = masks()
        ink = o | g
        ink[FLOOR:FLOOR + 2, 56:60] = True
        # cols 0..29 have nothing at the floor: the walk stops after the green
        got = ct.fill_under(o, po, g, pg, islands=False, ink=ink)
        self.assertEqual(got, list(range(30, 60)))


class FlushDescent(unittest.TestCase):

    def test_a_pale_descent_reaching_the_floor_starts_the_walk(self):
        o = np.zeros((H, N), bool); po = np.full(N, np.nan)
        g = np.zeros((H, N), bool); pg = np.full(N, np.nan)
        for c in range(0, 60):                    # orange flat at row 100
            o[100:102, c] = True; po[c] = 100.5
        o[100:140, 60] = True; po[60] = 110.0     # the descent's last classified column
        for c in range(62, N):                    # green along the floor after its own flush
            g[FLOOR:FLOOR + 2, c] = True; pg[c] = FLOOR + 0.5
        ink = o | g
        ink[110:H, 61] = True                     # the pale stroke down to the floor
        got = ct.fill_under(o, po, g, pg, islands=False, ink=ink)
        self.assertEqual(got, list(range(61, N)))
        self.assertTrue(np.allclose(po[62:], FLOOR + 0.5))

    def test_a_descent_that_stops_short_does_not(self):
        o = np.zeros((H, N), bool); po = np.full(N, np.nan)
        g = np.zeros((H, N), bool); pg = np.full(N, np.nan)
        for c in range(0, 60):
            o[100:102, c] = True; po[c] = 100.5
        o[100:140, 60] = True; po[60] = 110.0
        for c in range(62, N):
            g[FLOOR:FLOOR + 2, c] = True; pg[c] = FLOOR + 0.5
        ink = o | g
        ink[110:170, 61] = True                   # stops 27 rows above the floor
        self.assertEqual(ct.fill_under(o, po, g, pg, islands=False, ink=ink), [])



class StepInk(unittest.TestCase):

    def test_white_paper_is_not_ink_even_as_uint8(self):
        import step1
        img = np.full((30, 40, 3), 255, np.uint8)
        img[10:12, 5:30] = (213, 166, 126)           # an orange stroke
        img[20, :] = (207, 190, 116)                 # a khaki blend
        img[25, :] = (203, 200, 201)                 # a grey wash: not a pen
        img[27, :] = (0, 0, 0)                       # a black gridline: not a pen
        ink = step1._ink(img, 0, 30, 0, 40)
        self.assertEqual(int(ink.sum()), 2 * 25 + 40)
        self.assertFalse(ink[0].any())
        self.assertFalse(ink[25].any())
        self.assertFalse(ink[27].any())


if __name__ == "__main__":
    unittest.main()
