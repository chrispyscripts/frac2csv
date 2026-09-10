"""The "Frac Detail" grid on a Resource Energy Solutions daily completion.

Carmine, #615, on 01340: "you are getting the rotation on this test well but
it is not getting all the stage PDF shows they are there". Both halves are
true and about different things — the file's 290 pages hold only 26 vector
chart pages covering 13 zones, and the charts for the rest are not in it. What
IS in it, on 67 pages, is this grid: one row per stage pumped that day, all 28
of them.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import frac_detail as fd                                 # noqa: E402


class _Page(object):
    """Rows of (x, text) at 3pt spacing — the shape _rows() reads."""

    def __init__(self, rows):
        self._rows = rows

    def get_text(self, kind="text", *a, **k):
        if kind == "dict":
            blocks = []
            for i, row in enumerate(self._rows):
                y = 100.0 + i * 12.0
                blocks.append({"lines": [{"spans": [
                    {"text": t, "bbox": (x, y, x + 30, y + 8)}
                    for x, t in row]}]})
            return {"blocks": blocks}
        return "\n".join(" ".join(t for _x, t in row) for row in self._rows)


# 01340 p61, at the printed x positions, including the multi-line header
GRID = [
    [(285, "Frac Detail")],
    [(44, "Stg"), (74, "Date"), (109, "Start Time"), (160, "Depth"),
     (194, "Avg Treat"), (239, "Avg Slurry"), (297, "Max"),
     (348, "Proppant SIze"), (438, "Total"), (497, "Max"), (544, "Total")],
    [(166, "(m)"), (203, "Press"), (251, "Rate"), (294, "Slurry"),
     (430, "Proppant"), (478, "Concentration"), (543, "Stage")],
    [(203, "(MPa)"), (244, "(m3/min)"), (296, "Rate"), (436, "Placed"),
     (492, "(kg/m3)"), (548, "Vol")],
    [(290, "(m3/min)"), (444, "(t)"), (545, "(m3)")],
    [(40, "26"), (65, "11-02-25"), (105, "06:49:00 AM"), (163, "3638"),
     (206, "76.4"), (255, "7.2"), (301, "8.3"), (363, "50/140"),
     (442, "140"), (499, "600"), (544, "518.2")],
    [(40, "27"), (65, "11-02-25"), (105, "05:04:00 PM"), (163, "3540"),
     (209, "76"), (255, "7.7"), (301, "8.3"), (363, "50/140"),
     (442, "140"), (499, "600"), (544, "504.1")],
    [(486, "Daily Total"), (546, "1547")],
    [(288, "Time Log")],
    [(54, "00:00"), (101, "06:30"), (139, "6.50"), (164, "Fracture")],
]
# the page prints its own day in long form; the grid's short dates are checked
# against it
HEADER_DATE = [[(600, "Nov 2, 2025")]]


class Columns(unittest.TestCase):
    def test_names_are_assembled_from_the_multiline_header(self):
        cols, _rows = fd.parse_page(_Page(HEADER_DATE + GRID))
        self.assertEqual(cols, [
            "Stg", "Date", "Start Time", "Depth (m)", "Avg Treat Press (MPa)",
            "Avg Slurry Rate (m3/min)", "Max Slurry Rate (m3/min)",
            "Proppant SIze", "Total Proppant Placed (t)",
            "Max Concentration (kg/m3)", "Total Stage Vol (m3)"])

    def test_the_reports_own_typo_is_preserved(self):
        cols, _ = fd.parse_page(_Page(HEADER_DATE + GRID))
        self.assertIn("Proppant SIze", cols)


class Rows(unittest.TestCase):
    def test_the_data_rows(self):
        _cols, rows = fd.parse_page(_Page(HEADER_DATE + GRID))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0][:4], ["26", "11-02-25", "06:49:00 AM", "3638"])
        self.assertEqual(rows[1][0][0], "27")

    def test_daily_total_closes_the_grid(self):
        # 1547 is a day's total volume, not a stage
        _cols, rows = fd.parse_page(_Page(HEADER_DATE + GRID))
        self.assertTrue(all(r[0][0] in ("26", "27") for r in rows))

    def test_the_time_log_below_is_not_read_as_rows(self):
        _cols, rows = fd.parse_page(_Page(HEADER_DATE + GRID))
        self.assertEqual(len(rows), 2)

    def test_not_this_page(self):
        self.assertIsNone(fd.parse_page(_Page([[(90, "Daily Completion")]])))


class Stamp(unittest.TestCase):
    """mm-dd-yy, checked against the page's own long-form date.

    Not a guess: page 57 of 01340 prints "Oct 31, 2025" beside a row reading
    "10-31-25", and 31 is not a month.
    """

    def test_month_first(self):
        self.assertEqual(
            fd._stamp("11-02-25", "06:49:00 AM", [(2025, 11, 2)]),
            "2025-11-02 06:49:00")

    def test_the_case_that_proves_the_order(self):
        self.assertEqual(
            fd._stamp("10-31-25", "07:00:00 AM", [(2025, 10, 31)]),
            "2025-10-31 07:00:00")

    def test_pm_is_added(self):
        self.assertEqual(
            fd._stamp("11-02-25", "05:04:00 PM", [(2025, 11, 2)]),
            "2025-11-02 17:04:00")

    def test_noon_and_midnight(self):
        self.assertEqual(fd._stamp("11-02-25", "12:30:00 AM", [(2025, 11, 2)]),
                         "2025-11-02 00:30:00")
        self.assertEqual(fd._stamp("11-02-25", "12:30:00 PM", [(2025, 11, 2)]),
                         "2025-11-02 12:30:00")

    def test_a_date_the_page_does_not_print_is_refused(self):
        # rather than silently moving the stage to another month
        self.assertIsNone(
            fd._stamp("02-11-25", "06:49:00 AM", [(2025, 11, 2)]))

    def test_no_clock_still_gives_the_day(self):
        self.assertEqual(fd._stamp("11-02-25", "", [(2025, 11, 2)]),
                         "2025-11-02")

    def test_an_impossible_date(self):
        self.assertIsNone(fd._stamp("13-40-25", "06:49:00 AM", []))


class _Doc(object):
    def __init__(self, pages):
        self._pages = pages
        self.page_count = len(pages)

    def __getitem__(self, i):
        return self._pages[i]


class Document(unittest.TestCase):
    def test_date_and_time_fold_into_one_stamp(self):
        tab = fd.parse_document(_Doc([_Page(HEADER_DATE + GRID)]))
        self.assertEqual(tab["columns"][:2], ["Stg", "Start"])
        self.assertEqual(tab["rows"][0][1], "2025-11-02 06:49:00")

    def test_the_same_page_twice_is_one_set_of_rows(self):
        tab = fd.parse_document(
            _Doc([_Page(HEADER_DATE + GRID), _Page(HEADER_DATE + GRID)]))
        self.assertEqual(len(tab["rows"]), 2)

    def test_rows_come_out_in_stage_order(self):
        tab = fd.parse_document(_Doc([_Page(HEADER_DATE + GRID)]))
        self.assertEqual([r[0] for r in tab["rows"]], ["26", "27"])

    def test_a_document_with_no_grid(self):
        self.assertIsNone(
            fd.parse_document(_Doc([_Page([[(90, "Daily Completion")]])])))


if __name__ == "__main__":
    unittest.main()
