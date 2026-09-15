"""Stage depths on the payload: from the chart title, or joined from a table.

  python3 -m unittest tests.test_stage_depth
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                            # noqa: E402


class ParseInterval(unittest.TestCase):

    def test_step_and_trican_shapes(self):
        self.assertEqual(pipeline._parse_interval("2,702.50-2,802.50 m"), (2702.5, 2802.5))
        self.assertEqual(pipeline._parse_interval("4055.65 - 4056.65 m"), (4055.65, 4056.65))
        self.assertEqual(pipeline._parse_interval("3196.24 – 3196.34 m"), (3196.24, 3196.34))

    def test_nothing_is_none(self):
        self.assertEqual(pipeline._parse_interval(""), (None, None))
        self.assertEqual(pipeline._parse_interval("Stage 4"), (None, None))


class SetDepth(unittest.TestCase):

    def test_single_depth_is_both(self):
        m = {}
        pipeline._set_depth(m, 3492.1, 3492.1)
        self.assertEqual((m["top_m"], m["base_m"]), (3492.1, 3492.1))

    def test_never_overwrites(self):
        m = {"top_m": 1.0, "base_m": 2.0}
        pipeline._set_depth(m, 5.0, 6.0)
        self.assertEqual((m["top_m"], m["base_m"]), (1.0, 2.0))

    def test_ordered(self):
        m = {}
        pipeline._set_depth(m, 20.0, 10.0)
        self.assertEqual((m["top_m"], m["base_m"]), (10.0, 20.0))


class JoinFromTable(unittest.TestCase):

    def test_bj_totals_top_depth_reaches_the_chart(self):
        chart = {"type": "series", "meta": {"stage": "3"}}
        chart2 = {"type": "series", "meta": {"stage": "4", "top_m": 1.0, "base_m": 2.0}}
        table = {"type": "table", "columns": ["Interval #", "Start time", "Top Depth (m)", "ISIP (MPa)"],
                 "rows": [["3", "1/29/2025 16:39", "6455.00", "30.6"], ["4", "1/30/2025 2:57", "6385.00", "31"]]}
        pipeline._join_stage_depth([chart, chart2, table])
        self.assertEqual((chart["meta"]["top_m"], chart["meta"]["base_m"]), (6455.0, 6455.0))
        self.assertEqual((chart2["meta"]["top_m"], chart2["meta"]["base_m"]), (1.0, 2.0))

    def test_top_and_bottom_columns(self):
        chart = {"type": "series", "meta": {"stage": "7"}}
        table = {"type": "table", "columns": ["Stage", "Top Depth (mKB)", "Bottom Depth (mKB)"],
                 "rows": [["7", "2,411.5", "2,430.0"]]}
        pipeline._join_stage_depth([chart, table])
        self.assertEqual((chart["meta"]["top_m"], chart["meta"]["base_m"]), (2411.5, 2430.0))

    def test_no_depth_column_does_nothing(self):
        chart = {"type": "series", "meta": {"stage": "7"}}
        table = {"type": "table", "columns": ["Stage", "ISIP"], "rows": [["7", "30"]]}
        pipeline._join_stage_depth([chart, table])
        self.assertNotIn("top_m", chart["meta"])


if __name__ == "__main__":
    unittest.main()
