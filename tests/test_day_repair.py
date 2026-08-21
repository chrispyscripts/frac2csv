"""Making the printed DAYS agree with the clock printed beside them.

  python3 -m unittest tests.test_day_repair

A chart is a contiguous recording, so between two of its labels the day
advances exactly when the clock wraps past midnight, and not otherwise. OCR
misreads a day often enough that this is worth enforcing: 00915 p123 prints
2022/04/29 three times, reads the last as 2022/04/28, and the clock beside
them runs 20:40, 21:10, 21:40 — no wrap anywhere, so nothing may change day.
That page died with "implausible duration 161320s".

The rule picks the SHORTEST consistent reading rather than choosing a
direction, because choosing one by counting rollovers picks the wrong order:
read backwards, 01:27 / 00:22 / 23:17 never steps backwards and scores zero
rollovers against the correct order's one. Doing that broke 00915 p106, a
page that already worked, which is why the last two tests exist.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1

H = 3600


def rows(items):
    """(clock_seconds, y, m, d, cy) -> the tuples _day_repair works in."""
    return [({"t": "x", "cy": cy}, y, m, d, tod) for tod, y, m, d, cy in items]


def days(out):
    return [(y, m, d) for _, y, m, d, _ in out]


class DayRepair(unittest.TestCase):
    def test_00915_p123_no_wrap_so_no_day_may_change(self):
        # 20:40, 21:10, 21:40 printed 29, 29, 28
        out = lib1._day_repair(rows([
            (20 * H + 40 * 60, 2022, 4, 29, 100),
            (21 * H + 10 * 60, 2022, 4, 29, 200),
            (21 * H + 40 * 60, 2022, 4, 28, 300)]))
        self.assertEqual(days(out), [(2022, 4, 29)] * 3)

    def test_00915_p107_one_real_wrap_and_one_bad_day(self):
        # 23:17, 00:22, 01:27 printed 23, 24, 20
        out = lib1._day_repair(rows([
            (23 * H + 17 * 60, 2022, 4, 23, 100),
            (0 * H + 22 * 60, 2022, 4, 24, 200),
            (1 * H + 27 * 60, 2022, 4, 20, 300)]))
        self.assertEqual(days(out),
                         [(2022, 4, 23), (2022, 4, 24), (2022, 4, 24)])

    def test_a_genuine_midnight_crossing_is_left_alone(self):
        out = lib1._day_repair(rows([
            (23 * H + 17 * 60, 2022, 4, 23, 100),
            (0 * H + 22 * 60, 2022, 4, 24, 200),
            (1 * H + 27 * 60, 2022, 4, 24, 300)]))
        self.assertEqual(days(out),
                         [(2022, 4, 23), (2022, 4, 24), (2022, 4, 24)])

    def test_labels_already_right_are_returned_untouched(self):
        src = rows([(9 * H, 2022, 4, 23, 100), (10 * H, 2022, 4, 23, 200)])
        self.assertEqual(days(lib1._day_repair(src)), [(2022, 4, 23)] * 2)

    def test_a_crossing_at_the_end_of_a_month_still_works(self):
        out = lib1._day_repair(rows([
            (23 * H + 50 * 60, 2022, 4, 30, 100),
            (0 * H + 20 * 60, 2022, 5, 1, 200)]))
        self.assertEqual(days(out), [(2022, 4, 30), (2022, 5, 1)])

    def test_a_crossing_at_the_end_of_a_year(self):
        out = lib1._day_repair(rows([
            (23 * H + 50 * 60, 2021, 12, 31, 100),
            (0 * H + 20 * 60, 2022, 1, 1, 200)]))
        self.assertEqual(days(out), [(2021, 12, 31), (2022, 1, 1)])

    def test_00915_p106_two_labels_across_midnight_must_not_be_flattened(self):
        # THE REGRESSION. A wrap-count rule reads these backwards, finds zero
        # rollovers that way, and collapses both onto one day — turning a page
        # that worked into an implausible-duration failure.
        out = lib1._day_repair(rows([
            (23 * H + 17 * 60, 2022, 4, 23, 100),
            (0 * H + 22 * 60, 2022, 4, 24, 200)]))
        self.assertEqual(days(out), [(2022, 4, 23), (2022, 4, 24)])

    def test_one_label_is_returned_as_is(self):
        src = rows([(9 * H, 2022, 4, 23, 100)])
        self.assertEqual(days(lib1._day_repair(src)), [(2022, 4, 23)])

    def test_empty(self):
        self.assertEqual(lib1._day_repair([]), [])


if __name__ == "__main__":
    unittest.main()
