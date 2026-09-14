"""Layout B: the chart's own clock axis names sample 0 (00910 p90, #648).

  python3 -m unittest tests.test_trican_b_window_clock
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc                                 # noqa: E402


def page(start, elapsed, axis):
    return ({"start_time": start, "elapsed_s": elapsed},
            {"t0_seconds": float(axis), "duration_s": 2056, "notes": []})


class WindowClock(unittest.TestCase):

    def test_00910_p90_takes_the_axis_and_names_the_sheet(self):
        # Start Time 12:16, Elapsed 1:14:27, axis opening 12:57:39
        meta, info = tc._clock_from_axis(*page("12:16:00", 4467, 12 * 3600 + 57 * 60 + 39))
        self.assertEqual(meta["start_time"], "12:57:39")
        self.assertTrue(meta["clock_chart"])
        self.assertEqual(meta["printed_start"], "12:16")
        self.assertIn("42 min after the Start Time 12:16", info["notes"][0])
        self.assertIn("first 42 min of its 74 elapsed are not plotted", info["notes"][0])

    def test_the_same_minute_stays_as_printed(self):
        meta, info = tc._clock_from_axis(*page("11:42:00", 2011, 11 * 3600 + 42 * 60 + 1))
        self.assertEqual(meta["start_time"], "11:42:00")
        self.assertNotIn("clock_chart", meta)
        self.assertEqual(info["notes"], [])

    def test_a_window_opening_a_few_minutes_early_is_the_axis_too(self):
        meta, info = tc._clock_from_axis(*page("11:42:00", 2011, 11 * 3600 + 37 * 60))
        self.assertEqual(meta["start_time"], "11:37:00")
        self.assertIn("5 min before", info["notes"][0])

    def test_01350_p186_is_left_as_printed_and_said(self):
        # Start Time 02:41 under an axis reading 12:50: ten hours, outside any envelope
        meta, info = tc._clock_from_axis(*page("02:41:00", 3600, 12 * 3600 + 50 * 60))
        self.assertEqual(meta["start_time"], "02:41:00")
        self.assertNotIn("clock_chart", meta)
        self.assertIn("cannot hold", info["notes"][0])

    def test_no_elapsed_allows_ten_minutes_either_way(self):
        meta, _ = tc._clock_from_axis(*page("12:16:00", 0, 12 * 3600 + 24 * 60))
        self.assertEqual(meta["start_time"], "12:24:00")
        meta, _ = tc._clock_from_axis(*page("12:16:00", 0, 12 * 3600 + 57 * 60))
        self.assertEqual(meta["start_time"], "12:16:00")

    def test_no_axis_or_no_printed_start_does_nothing(self):
        m, i = tc._clock_from_axis({"start_time": ""}, {"t0_seconds": 100.0, "notes": []})
        self.assertEqual(m["start_time"], "")
        m, i = tc._clock_from_axis({"start_time": "12:16:00"}, {"t0_seconds": None, "notes": []})
        self.assertEqual(m["start_time"], "12:16:00")


if __name__ == "__main__":
    unittest.main()
