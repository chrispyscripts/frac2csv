"""Tables carry the stage's label, date and start time from the chart list.

  python3 -m unittest tests.test_stage_join

Carmine, 2026-09-14: "tables are leaving stage name and date / time blank for
all types. That data is available on the stage list." It is — on the charts —
and the join is by stage number, with the Lab's own guards.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                            # noqa: E402


def series(stage, date="2025-03-01", start="01:18:58", source="STEP surface chart (raster)"):
    return {"type": "series", "source": source, "meta": {"stage": stage, "date": date, "start_time": start},
            "samples": [], "data": {}}


def table(columns, rows, title="Daily Stage Summary"):
    return {"type": "table", "title": title, "columns": list(columns), "rows": [list(r) for r in rows]}


class Join(unittest.TestCase):

    def test_a_stage_table_gets_the_three_columns_after_its_stage(self):
        t = table(["UWI", "Stage", "Top Depth (m)"], [["x", "1", "6552.5"], ["x", "2", "6600.0"]])
        res = [series("1"), series("2", start="03:40:00"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["columns"], ["UWI", "Stage", "Stage Label", "Date", "Start Time", "Top Depth (m)"])
        self.assertEqual(t["rows"][0], ["x", "1", "1", "2025-03-01", "01:18:58", "6552.5"])
        self.assertEqual(t["rows"][1][4], "03:40:00")

    def test_surface_and_chemical_charts_of_one_stage_agree(self):
        t = table(["Stage", "Max"], [["7", "60"]])
        res = [series("7"), series("7", source="STEP chemical chart (raster)"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["rows"][0][1:4], ["7", "2025-03-01", "01:18:58"])

    def test_calfrac_surface_and_bh_sheets_agree_and_drop_the_suffix(self):
        t = table(["Zone #", "Max"], [["21", "60"]])
        res = [series("21 Surface", source="CalFrac chart"), series("21 BH", source="CalFrac chart"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["rows"][0][1], "21")

    def test_two_charts_on_two_clocks_leave_it_blank(self):
        t = table(["Interval #", "Max"], [["5", "60"]])
        res = [series("5"), series("5 (2)", start="11:00:00"), t]      # BJ 00636: a gel pill on its own axis
        pipeline._join_stage_meta(res)
        self.assertEqual(t["rows"][0][1:4], ["", "2025-03-01", ""])   # the date agrees, the clock does not

    def test_a_table_with_its_own_date_and_start_gets_only_the_label(self):
        t = table(["UWI", "stage", "date", "start", "finish"], [["x", "3", "2015-07-06", "05:32", "06:31"]])
        res = [series("3", date="2015-07-06", start="17:32:00"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["columns"], ["UWI", "stage", "Stage Label", "date", "start", "finish"])

    def test_no_clock_on_the_chart_stays_blank(self):
        t = table(["Stage", "Max"], [["4", "60"]])
        res = [series("4", date="", start="00:00:00"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["rows"][0][1:4], ["4", "", ""])

    def test_a_table_without_a_stage_column_is_untouched(self):
        t = table(["UWI", "Casing OD", "Weight"], [["x", "139.7", "25.3"]], title="Tubular Data")
        res = [series("1"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["columns"], ["UWI", "Casing OD", "Weight"])

    def test_an_interval_column_of_names_is_not_a_stage_column(self):
        t = table(["Interval", "Max"], [["Montney Upper", "60"], ["Montney Lower", "61"]])
        res = [series("1"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["columns"], ["Interval", "Max"])

    def test_canyon_treatment_log_joins_on_interval(self):
        t = table(["UWI", "Interval", "Stage Number", "Time", "Comments"], [["", "1", "1", "2017-08-06", "Pad"]],
                  title="Treatment Log")
        res = [series("1", date="2017-08-06", start="10:32:07", source="Canyon chart"), t]
        pipeline._join_stage_meta(res)
        self.assertEqual(t["columns"][:5], ["UWI", "Interval", "Stage Label", "Date", "Start Time"])
        self.assertEqual(t["rows"][0][2:5], ["1", "2017-08-06", "10:32:07"])


if __name__ == "__main__":
    unittest.main()
