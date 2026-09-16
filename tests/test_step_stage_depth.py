"""A STEP chart numbered by its interval's Top Depth on the Daily Stage Summary (00180-1021).

  python3 -m unittest tests.test_step_stage_depth
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                            # noqa: E402

TABLE = {"columns": ["Stage", "Top Depth (m)", "Bottom Depth (m)", "Date (YYYY-MM-DD)"],
         "rows": [["1", "6,937.0", "7,001.3", "2019-05-17"], ["2", "6,837.0", "6,877.3", "2019-05-17"],
                  ["5", "6,727.0", "6,777.3", "2019-05-18"]]}


def chart(stage, top):
    return {"type": "series", "source": "STEP surface chart (raster)",
            "meta": {"stage": stage, "title": f"Interval {stage or '?'}", "top_m": top, "base_m": top + 40}}


class StageFromDepth(unittest.TestCase):

    def test_a_lost_number_is_taken_from_the_sheet(self):
        c = chart("", 6837.0)
        self.assertEqual(pipeline._stage_from_depth([c], TABLE), 1)
        self.assertEqual(c["meta"]["stage"], "2")
        self.assertIn("Top Depth 6837", c["meta"]["warnings"][0])

    def test_a_numbered_chart_is_left_alone(self):
        c = chart("5", 6727.0)
        self.assertEqual(pipeline._stage_from_depth([c], TABLE), 0)
        self.assertEqual(c["meta"]["stage"], "5")

    def test_a_depth_on_no_row_is_left_blank(self):
        c = chart("", 6500.0)
        self.assertEqual(pipeline._stage_from_depth([c], TABLE), 0)
        self.assertEqual(c["meta"]["stage"], "")

    def test_no_table_does_nothing(self):
        self.assertEqual(pipeline._stage_from_depth([chart("", 6837.0)], None), 0)


if __name__ == "__main__":
    unittest.main()
