"""Turning the fitted time axis into a date and a clock.

  python3 -m unittest tests.test_stamp

The fit runs through OCR'd label centroids, so it lands a hair either side of
the second it means. Truncating that made every Liberty start time a second
short — 09:44:59 for a sheet printing 09:45, 19:59:59 for 20:00.

Harmless until the chart starts at midnight. Then 00:00:00 truncates to
23:59:59 on the day BEFORE, the date follows it back, and a chart whose clock
is perfect trips the backwards-clock warning on the stage beside it. Carmine
found it on 00269 stage 15 (issues #601, #606): the axis reads 2023/01/17
00:00 and we reported Jan 16.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1

DAY = 86400
# the module's epoch: absolute seconds counted from 2000-01-01
def at(days, h=0, m=0, s=0, frac=0.0):
    return days * DAY + h * 3600 + m * 60 + s + frac


class Stamp(unittest.TestCase):
    def test_a_hair_under_the_second_rounds_up(self):
        # the real shape of the bug: 09:45 arriving as 35099.9997
        self.assertEqual(lib1._stamp(at(725, 9, 45) - 0.0003)[1], "09:45:00")

    def test_a_hair_over_the_second_rounds_down(self):
        self.assertEqual(lib1._stamp(at(725, 9, 45) + 0.0003)[1], "09:45:00")

    def test_exactly_on_the_second_is_unchanged(self):
        self.assertEqual(lib1._stamp(at(725, 9, 45))[1], "09:45:00")

    def test_THE_MIDNIGHT_CASE(self):
        # 00269 stage 15. A hair under midnight must not become the day before.
        d, c = lib1._stamp(at(8418) - 0.0003)
        self.assertEqual(c, "00:00:00")
        self.assertEqual(d, lib1._stamp(at(8418))[0])

    def test_the_date_and_the_clock_come_from_one_instant(self):
        # they cannot disagree, whatever the fraction is
        for frac in (-0.4, -0.0001, 0.0, 0.0001, 0.4):
            d, c = lib1._stamp(at(8418) + frac)
            self.assertEqual((d, c), (lib1._stamp(at(8418))[0], "00:00:00"))

    def test_a_second_before_midnight_is_still_the_day_before(self):
        # rounding must not swallow a real 23:59:59
        d1, c1 = lib1._stamp(at(8418) - 1)
        d2, _ = lib1._stamp(at(8418))
        self.assertEqual(c1, "23:59:59")
        self.assertNotEqual(d1, d2)

    def test_the_epoch_is_2000_01_01(self):
        self.assertEqual(lib1._stamp(0), ("2000-01-01", "00:00:00"))

    def test_it_crosses_a_year_boundary(self):
        d, c = lib1._stamp(at(366) - 0.0002)      # 2000 was a leap year
        self.assertEqual((d, c), ("2001-01-01", "00:00:00"))

    def test_noon_and_the_last_second_of_a_day(self):
        self.assertEqual(lib1._stamp(at(100, 12))[1], "12:00:00")
        self.assertEqual(lib1._stamp(at(100, 23, 59, 59))[1], "23:59:59")


if __name__ == "__main__":
    unittest.main()
