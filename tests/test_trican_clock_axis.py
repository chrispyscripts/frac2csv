"""Layout A's own "Clock Time (hour:min)" axis (00041, #645).

  python3 -m unittest tests.test_trican_clock_axis
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc                                 # noqa: E402

# 00041 p73 as the strip reads: eight labels, ten minutes apart, over a frame
# 107..898 px wide carrying 69.2 min — 5.248 s per pixel from the elapsed axis
X0, TB = 107, 69.2 * 60.0 / 791.0
P73 = [(21 * 3600 + 38 * 60, 107), (21 * 3600 + 48 * 60, 221),
       (21 * 3600 + 58 * 60, 336), (22 * 3600 + 8 * 60, 450),
       (22 * 3600 + 18 * 60, 564), (22 * 3600 + 28 * 60, 679),
       (22 * 3600 + 38 * 60, 793), (22 * 3600 + 48 * 60, 898)]


def origin(pts, x0=X0, tb=TB):
    got = tc._clock_origin(pts, x0, tb)
    return None if got is None else (round(got[0]), got[1], got[2])


class ClockOrigin(unittest.TestCase):

    def test_p73_reads_21_38(self):
        o, agree, read = origin(P73)
        self.assertEqual((agree, read), (8, 8))
        self.assertAlmostEqual(o, 21 * 3600 + 38 * 60, delta=45)

    def test_one_misread_hour_loses_the_vote(self):
        # "22:08" read as "23:08": twelve labels' worth of wrong, one reading
        pts = list(P73)
        pts[3] = (23 * 3600 + 8 * 60, 450)
        o, agree, read = origin(pts)
        self.assertEqual((agree, read), (7, 8))
        self.assertAlmostEqual(o, 21 * 3600 + 38 * 60, delta=45)

    def test_midnight_crossing_is_the_next_day(self):
        # 00041 p77: 23:40 .. 00:45, the later labels earlier on the clock
        pts = [((23 * 3600 + 40 * 60 + k * 600) % 86400, 107 + k * 113)
               for k in range(7)]
        o, agree, read = origin(pts, tb=600.0 / 113.0)
        self.assertEqual((agree, read), (7, 7))
        self.assertAlmostEqual(o, 23 * 3600 + 40 * 60, delta=45)

    def test_origin_is_folded_to_a_day(self):
        # a chart opening 00:05 whose first label reads 00:05 stays 00:05
        pts = [(5 * 60 + k * 600, 107 + k * 113) for k in range(7)]
        o, *_ = origin(pts, tb=600.0 / 113.0)
        self.assertAlmostEqual(o, 5 * 60, delta=45)

    def test_fewer_than_three_labels_is_no_reading(self):
        self.assertIsNone(origin(P73[:2]))

    def test_labels_off_the_elapsed_scale_are_no_reading(self):
        # the same labels against a slope twice as steep: no three agree
        self.assertIsNone(origin(P73, tb=TB * 2))

    def test_no_slope_is_no_reading(self):
        self.assertIsNone(origin(P73, tb=None))
        self.assertIsNone(origin(P73, tb=0.0))


if __name__ == "__main__":
    unittest.main()
