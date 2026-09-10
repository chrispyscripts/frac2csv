"""Per-interval frac summary sheets (00900-00905).

Six filings reported "no extractable charts or tables found ... no page in it
draws a plotted curve". True of the charts — they are bitmaps — and it said
nothing about the 323 stages of text printed above them.

The cases here are all real sheets from those files, including the four that
were parsed wrong before they were looked at:

  * "40/70 Sand:" — a label that STARTS with a digit. Read as a value, it
    took the three proppant-mesh columns out of every row.
  * "INT9" with no space, on 30 of 00901's 53 sheets.
  * "22-Nov-2021 Pump Time:" — the date sharing one span with the next
    label, which read no clock at all on those sheets.
  * "(~15mins to reset)" — an operator's note ABOVE a printed pump time of
    240, taken as the pump time by a page-wide search.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import interval_sheet as isheet                          # noqa: E402


class _Page(object):
    """A page built from rows of (x, text), the shape _rows() reads."""

    def __init__(self, rows):
        self._rows = rows

    def get_text(self, kind="text", *a, **k):
        if kind == "dict":
            blocks = []
            for i, row in enumerate(self._rows):
                y = 8.0 + i * 16.0
                blocks.append({"lines": [{"spans": [
                    {"text": t, "bbox": (x, y, x + 40, y + 8)}
                    for x, t in row]}]})
            return {"blocks": blocks}
        return "\n".join(" ".join(t for _x, t in row) for row in self._rows)


# 00900 p52, interval 1 — every field the sheet prints
SHEET1 = [
    [(90, "BLACK SWAN HZ NIG CREEK B-A010-B/094-H-04")],
    [(489, "Clean Fluid:"), (570, "282.0  m3"),
     (672, "Total Sand Placed:"), (795, "30.0  tonne")],
    [(90, "INT 1"), (489, "Ball Max:"), (580, "0.0  MPa"),
     (702, "40/70 Sand:"), (795, "15.0  tonne")],
    [(89, "Sleeve Depth:   5111 m"), (489, "Avg Press:"), (575, "73.0  MPa"),
     (696, "30/50 Sand:"), (795, "10.0  tonne")],
    [(489, "Avg Rate"), (580, "8.4  m3/min"),
     (671, "30/50 PrimePlus:"), (800, "5.0  tonne")],
    [(90, "Start Date:"), (192, "4:14:00 AM"), (315, "25-Nov-2021"),
     (411, "Pump Time:"), (489, "Max Press:"), (575, "77.0 Mpa")],
    [(90, "End Date:"), (192, "5:09:00 AM"), (315, "25-Nov-2021"),
     (411, "55 mins"), (489, "Max rate:"), (580, "8.8  m3/min"),
     (689, "Max Prop Con:"), (798, "200  kgPA")],
    [(89, "Notes:")],
]

# 00904 p100: "INT49" closed up, and the date merged with the next label
SHEET_MERGED = [
    [(90, "BLACK SWAN HZ NIG CREEK C-100-J/094-A-13"),
     (489, "Clean Fluid:"), (570, "293.0 m3")],
    [(90, "INT49"), (489, "Ball Max:"), (580, "35.0 MPa"),
     (702, "40/70 Sand:"), (795, "30.0 tonne")],
    [(90, "Start Date:"), (192, "4:38:00 PM"),
     (315, "22-Nov-2021 Pump Time:"), (489, "Max Press:"), (575, "48.0Mpa")],
    [(90, "End Date:"), (192, "5:14:00 PM"), (315, "22-Nov-2021 36 mins"),
     (489, "Max rate:"), (580, "10.0 m3/min"),
     (689, "Total Sand Placed:"), (798, "75.0 tonne")],
]


def _sheet(start_clock, start_date, end_clock, end_date, mins, extra=None):
    return [
        [(90, "BLACK SWAN HZ"), (489, "Total Sand Placed:"), (570, "75.0 tonne")],
        [(90, "INT 7"), (489, "Clean Fluid:"), (570, "300.0 m3")],
        [(90, "Start Date:"), (192, start_clock), (315, start_date),
         (411, "Pump Time:")],
        [(90, "End Date:"), (192, end_clock), (315, end_date),
         (411, f"{mins} mins")],
    ] + ([[(89, extra)]] if extra else [])


class Fields(unittest.TestCase):
    def test_every_printed_field(self):
        r = isheet.parse_page(_Page(SHEET1))
        self.assertEqual(r["Stage"], "1")
        self.assertEqual(r["Start"], "2021-11-25 04:14:00")
        self.assertEqual(r["End"], "2021-11-25 05:09:00")
        self.assertEqual(r["Pump Time (min)"], "55")
        self.assertEqual(r["Clean Fluid (m3)"], "282.0")
        self.assertEqual(r["Total Sand Placed (tonne)"], "30.0")
        self.assertEqual(r["Ball Max (MPa)"], "0.0")
        self.assertEqual(r["Sleeve Depth (m)"], "5111")
        self.assertEqual(r["Avg Press (MPa)"], "73.0")
        self.assertEqual(r["Max Press (Mpa)"], "77.0")
        self.assertEqual(r["Max rate (m3/min)"], "8.8")
        self.assertEqual(r["Max Prop Con (kgPA)"], "200")

    def test_labels_that_start_with_a_digit(self):
        # the proppant meshes: read as values, they vanished from every row
        r = isheet.parse_page(_Page(SHEET1))
        self.assertEqual(r["40/70 Sand (tonne)"], "15.0")
        self.assertEqual(r["30/50 Sand (tonne)"], "10.0")
        self.assertEqual(r["30/50 PrimePlus (tonne)"], "5.0")

    def test_a_label_with_no_colon(self):
        self.assertEqual(
            isheet.parse_page(_Page(SHEET1))["Avg Rate (m3/min)"], "8.4")

    def test_int_closed_up_and_a_merged_date_span(self):
        r = isheet.parse_page(_Page(SHEET_MERGED))
        self.assertEqual(r["Stage"], "49")
        self.assertEqual(r["Start"], "2021-11-22 16:38:00")
        self.assertEqual(r["End"], "2021-11-22 17:14:00")
        self.assertEqual(r["Pump Time (min)"], "36")
        self.assertEqual(r["Max Press (Mpa)"], "48.0")

    def test_pump_time_comes_from_the_end_row_not_the_page(self):
        # 00905 interval 6: the note is ABOVE a printed 240
        p = _Page(_sheet("2:21:00 AM", "29-Nov-2021", "6:21:00 AM",
                         "29-Nov-2021", 240, extra="(~15mins to reset)"))
        self.assertEqual(isheet.parse_page(p)["Pump Time (min)"], "240")

    def test_not_a_sheet(self):
        self.assertIsNone(isheet.parse_page(_Page([[(90, "Well Name :")]])))


class Detect(unittest.TestCase):
    def test_both_marks_are_required(self):
        # "Total Sand Placed" alone is on the operator's DAILY pages too
        self.assertFalse(isheet.detect(
            _Page([[(90, "Total Sand Placed:"), (200, "75.0 tonne")]])))
        self.assertTrue(isheet.detect(_Page(SHEET1)))


class Reconcile(unittest.TestCase):
    """The sheet's own third number decides which reading is meant."""

    def test_a_stage_that_crosses_midnight(self):
        # 00900 interval 27: both rows print 26-Nov
        r = isheet.parse_page(_Page(_sheet(
            "11:36:00 PM", "26-Nov-2021", "12:14:00 AM", "26-Nov-2021", 38)))
        self.assertEqual(r["End"], "2021-11-26 00:14:00")   # as printed
        self.assertTrue(isheet.reconcile(r))
        self.assertEqual(r["End"], "2021-11-27 00:14:00")

    def test_twelve_pm_printed_for_twelve_am(self):
        # 00901 interval 4
        r = isheet.parse_page(_Page(_sheet(
            "10:49:00 PM", "18-Nov-2021", "12:01:00 PM", "19-Nov-2021", 72)))
        self.assertTrue(isheet.reconcile(r))
        self.assertEqual(r["End"], "2021-11-19 00:01:00")

    def test_a_consistent_sheet_is_left_alone(self):
        r = isheet.parse_page(_Page(_sheet(
            "4:14:00 AM", "25-Nov-2021", "5:09:00 AM", "25-Nov-2021", 55)))
        self.assertFalse(isheet.reconcile(r))
        self.assertEqual(r["End"], "2021-11-25 05:09:00")

    def test_an_arbitrary_disagreement_is_NOT_guessed_at(self):
        # 00901 interval 38: 3:25 AM to 9:41 AM, printed 41 mins. No day roll
        # and no 12-hour flip explains it, so it stays exactly as printed and
        # stays visible.
        r = isheet.parse_page(_Page(_sheet(
            "3:25:00 AM", "20-Nov-2021", "9:41:00 AM", "20-Nov-2021", 41)))
        self.assertFalse(isheet.reconcile(r))
        self.assertEqual(r["End"], "2021-11-20 09:41:00")

    def test_the_flip_is_offered_only_for_an_ambiguous_hour(self):
        # 9:41 is not 21:41 to any reader; only a 12 is ambiguous
        r = {"Start": "2021-11-20 03:25:00", "End": "2021-11-20 09:41:00",
             "Pump Time (min)": "1336"}
        self.assertFalse(isheet.reconcile(r))


class _Doc(object):
    def __init__(self, pages):
        self._pages = pages
        self.page_count = len(pages)

    def __getitem__(self, i):
        return self._pages[i]


class Document(unittest.TestCase):
    def test_an_identical_sheet_printed_twice_is_one_stage(self):
        # 00904 pages 100 and 101 are the same interval-49 sheet field for field
        doc = _Doc([_Page(SHEET_MERGED), _Page(SHEET_MERGED)])
        tab = isheet.parse_document(doc)
        self.assertEqual(len(tab["rows"]), 1)

    def test_a_retreat_of_one_interval_keeps_both_rows(self):
        # same INT, different clocks: two treatments, not a duplicated page
        a = _sheet("4:38:00 PM", "22-Nov-2021", "5:14:00 PM", "22-Nov-2021", 36)
        b = _sheet("9:10:00 AM", "23-Nov-2021", "9:44:00 AM", "23-Nov-2021", 34)
        tab = isheet.parse_document(_Doc([_Page(a), _Page(b)]))
        self.assertEqual(len(tab["rows"]), 2)

    def test_columns_are_the_union_and_stage_leads(self):
        doc = _Doc([_Page(SHEET1), _Page(SHEET_MERGED)])
        tab = isheet.parse_document(doc)
        self.assertEqual(tab["columns"][:4],
                         ["Stage", "Start", "End", "Pump Time (min)"])
        # a mesh printed on only one of the two sheets still gets a column
        self.assertIn("30/50 PrimePlus (tonne)", tab["columns"])

    def test_rows_come_out_in_stage_order(self):
        doc = _Doc([_Page(SHEET_MERGED), _Page(SHEET1)])   # 49 then 1
        tab = isheet.parse_document(doc)
        self.assertEqual([r[0] for r in tab["rows"]], ["1", "49"])

    def test_no_sheets_means_no_table(self):
        self.assertIsNone(
            isheet.parse_document(_Doc([_Page([[(90, "Well Name :")]])])))


if __name__ == "__main__":
    unittest.main()
