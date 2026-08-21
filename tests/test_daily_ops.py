"""The operator's daily report as a date and clock source.

The rows here are copied from the corpus, including their quirks — the two
column layouts, and the comment that ends "Frac Stage #" with no number.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import daily_ops                                         # noqa: E402

# 00121's layout: start, end, hours+code, activity, comment
PAGE_A = """Regulatory_Daily Completion and Workover
Report #  9.0,  Report Date:   1/30/2019
Time Log
16:00
16:30
0.50 ACID
Acid Wash/Squeeze
Acid Stage #10. Equalized to wellbore pressure and ready to Frac Stage #
16:30
17:15
0.75 inactive
inactive
Waited on adjacent well operations, ready to Frac Stage #10.
17:15
18:30
1.25 FRAC
Frac. Job
Started pumping on Stage #10.
"""

# 00020's layout: an extra cumulative-hours column
PAGE_B = """Daily Completion Operations
Report Date:   6/18/2019
08:00
11:30
3.50
11.50 FRAC
PP
Displaced acid to toe with pump down unit. Frac Stage # 1 (Perforated toe)
11:30
13:00
1.50
13.00 RU/RD
PP
Rigged down.
"""


class Rows(unittest.TestCase):
    def test_a_row_is_bounded_by_the_next_row(self):
        # The trap: a comment ending "Frac Stage #" is followed by the NEXT
        # row's clock, and a regex allowed to run past the boundary reads
        # "16:30" as stage 16.
        r = daily_ops.rows(PAGE_A)
        self.assertEqual([x[0] for x in r], ["16:00", "16:30", "17:15"])
        self.assertNotIn("17:15", r[0][1].split("\n", 1)[1])

    def test_both_column_layouts_are_read(self):
        self.assertEqual([x[0] for x in daily_ops.rows(PAGE_B)],
                         ["08:00", "11:30"])


class StageTimes(unittest.TestCase):
    def test_only_frac_rows_count(self):
        # the ACID row also names stage 10; pumping began at 17:15, not 16:00
        self.assertEqual(daily_ops.stage_times(PAGE_A), {10: "17:15"})

    def test_the_dangling_hash_is_not_read_as_a_stage(self):
        self.assertNotIn(16, daily_ops.stage_times(PAGE_A))

    def test_extra_column_layout(self):
        self.assertEqual(daily_ops.stage_times(PAGE_B), {1: "08:00"})


class ReportDate(unittest.TestCase):
    def test_reads_both_headers(self):
        self.assertEqual(daily_ops.report_date(PAGE_A), "2019-01-30")
        self.assertEqual(daily_ops.report_date(PAGE_B), "2019-06-18")

    def test_rejects_nonsense(self):
        self.assertIsNone(daily_ops.report_date("Report Date:   13/45/1200"))


class Index(unittest.TestCase):
    class _Doc:
        def __init__(self, pages):
            self._p = pages
            self.page_count = len(pages)

        def __getitem__(self, i):
            class _P:
                def __init__(self, t):
                    self._t = t

                def get_text(self):
                    return self._t
            return _P(self._p[i])

    def test_indexes_across_pages(self):
        got = daily_ops.index(self._Doc([PAGE_A, PAGE_B]))
        self.assertEqual(got[10], {"date": "2019-01-30", "start": "17:15:00"})
        self.assertEqual(got[1], {"date": "2019-06-18", "start": "08:00:00"})

    def test_a_stage_claimed_by_two_days_is_dropped(self):
        # An undated chart is a visible gap; a chart stamped off the wrong day
        # is a wrong answer wearing a date.
        other = PAGE_B.replace("6/18/2019", "6/19/2019")
        got = daily_ops.index(self._Doc([PAGE_B, other]))
        self.assertNotIn(1, got)

    def test_ignores_pages_that_are_not_daily_reports(self):
        self.assertEqual(daily_ops.index(self._Doc(["Zone 3 Summary\n08:00\n09:00\nFRAC Stage # 2"])), {})


if __name__ == "__main__":
    unittest.main()
