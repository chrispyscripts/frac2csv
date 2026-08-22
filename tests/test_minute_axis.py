"""Liberty charts that plot ELAPSED MINUTES instead of a wall clock.

  python3 -m unittest tests.test_minute_axis

Not every Liberty chart carries a clock. One variant captions its time axis
"Time (min)" and runs 0.00, 11.00, 22.00, 33.00, 44.00, 55.00 with no clock
and no date printed anywhere on the sheet. Every curve and every value axis on
those pages reads perfectly; the whole page was being thrown away for want of
a clock it never had — 27 of the 36 "time labels not found" failures in a
199-file sweep.

The caption is REQUIRED. A bare numeric ladder is indistinguishable from a
value axis, and guessing would put a chart on an invented timeline.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1


def sp(t, cx, cy, color=0):
    return {"t": t, "cx": cx, "cy": cy, "color": color}


def ladder(cx=498.3, vals=(0, 11, 22, 33, 44, 55), y0=682.2, dy=-112.9):
    return [sp(f"{v:.2f}", cx, y0 + i * dy) for i, v in enumerate(vals)]


CAP = sp("Time (min)", 517.6, 438.6)


class MinuteTicks(unittest.TestCase):
    def test_the_real_00628_ladder(self):
        got = lib1._minute_ticks(ladder() + [CAP])
        self.assertEqual([v for v, _ in got], [0.0, 11.0, 22.0, 33.0, 44.0, 55.0])

    def test_no_caption_means_no_ladder(self):
        # a value axis must never be read as time
        self.assertEqual(lib1._minute_ticks(ladder()), [])

    def test_a_value_axis_beside_the_caption_is_not_swept_in(self):
        # 00628 p101: the concentration axis puts its "0.0" 17pt away, and one
        # stray tick used to break the even-step test for the whole page
        spans = ladder() + [CAP, sp("0.0", 481.5, 718.6), sp("0.400", 481.5, 640.0)]
        got = lib1._minute_ticks(spans)
        self.assertEqual([v for v, _ in got], [0.0, 11.0, 22.0, 33.0, 44.0, 55.0])

    def test_coloured_ticks_are_not_the_time_ladder(self):
        spans = [sp(f"{v}", 498.3, 700 - 100 * i, color=0xFF0000)
                 for i, v in enumerate((0, 11, 22))] + [CAP]
        self.assertEqual(lib1._minute_ticks(spans), [])


class MinuteAxis(unittest.TestCase):
    def test_it_fits_seconds_against_position(self):
        (a, b), date, win = lib1._minute_axis(ladder() + [CAP])
        self.assertEqual(date, "")          # these sheets print no date
        self.assertIsNone(win)
        # 0 min at cy 682.2 and 55 min at the top
        self.assertAlmostEqual(a + b * 682.2, 0.0, places=3)
        self.assertAlmostEqual(a + b * (682.2 - 5 * 112.9), 55 * 60, places=2)

    def test_no_caption_no_axis(self):
        self.assertEqual(lib1._minute_axis(ladder()), (None, "", None))

    def test_two_ticks_are_not_enough(self):
        self.assertEqual(
            lib1._minute_axis(ladder(vals=(0, 11), y0=682.2) + [CAP]),
            (None, "", None))

    def test_an_uneven_ladder_is_refused(self):
        # even steps are what tells a time ladder from a value one
        bad = ladder(vals=(0, 11, 40, 55)) + [CAP]
        self.assertEqual(lib1._minute_axis(bad), (None, "", None))

    def test_a_ladder_that_does_not_ascend_is_refused(self):
        self.assertEqual(
            lib1._minute_axis(ladder(vals=(0, 0, 0)) + [CAP]), (None, "", None))

    def test_the_caption_is_matched_loosely_enough(self):
        for text in ("Time (min)", "Time(min)", "time (mins)", "Time  ( min )"):
            spans = ladder() + [sp(text, 517.6, 438.6)]
            self.assertEqual(len(lib1._minute_ticks(spans)), 6, text)


if __name__ == "__main__":
    unittest.main()
