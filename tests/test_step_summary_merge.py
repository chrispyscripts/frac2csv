"""The Daily Stage Summary's pages name one column one way (00180-1021).

  python3 -m unittest tests.test_step_summary_merge
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import step_summary as ss                                  # noqa: E402


class FakeDoc:
    page_count = 2

    def __getitem__(self, i):
        return i


class MergeAcrossPages(unittest.TestCase):

    def setUp(self):
        self._is, self._parse = ss.is_stage_summary_page, ss._parse_page
        ss.is_stage_summary_page = lambda pg: True
        pages = {
            0: (["1", "2"], [("Top Depth", "m", {0: "6937.0", 1: "6887.0"}),
                             ("Date", "YYYY-MM-DD", {0: "2019-05-17", 1: "2019-05-19"}),
                             ("Start Time", "hh:mm", {0: "13:39", 1: "03:41"})]),
            1: (["11", "12"], [("Top Depth", "m", {0: "6367.0", 1: "6307.0"}),
                               ("Date YYYY-MM-DD", "", {0: "2019-05-22", 1: "2019-05-22"}),
                               ("Start Time", "hh:mm", {0: "10:56", 1: "17:52"})]),
        }
        ss._parse_page = lambda pg: pages[pg]

    def tearDown(self):
        ss.is_stage_summary_page, ss._parse_page = self._is, self._parse

    def test_the_date_column_is_one_column(self):
        t = ss.parse_stage_summary(FakeDoc())
        self.assertEqual(t["columns"], ["Stage", "Top Depth (m)", "Date (YYYY-MM-DD)",
                                        "Start Time (hh:mm)"])
        self.assertEqual([r[2] for r in t["rows"]],
                         ["2019-05-17", "2019-05-19", "2019-05-22", "2019-05-22"])

    def test_every_stage_gets_its_date_on_the_clock(self):
        clocks = ss.stage_clock(FakeDoc())
        self.assertEqual(clocks["11"], {"date": "2019-05-22", "start": "10:56:00"})
        self.assertEqual(clocks["12"], {"date": "2019-05-22", "start": "17:52:00"})

    def test_a_date_cell_with_a_time_still_reads(self):
        self.assertEqual(ss._iso_date("2019-05-22 00:00:00"), "2019-05-22")
        self.assertEqual(ss._iso_date("2019/05/22"), "2019-05-22")
        self.assertEqual(ss._iso_date("22/05/2019"), "")


if __name__ == "__main__":
    unittest.main()
