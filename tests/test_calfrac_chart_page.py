"""Which MView pages are charts — the title, wherever it lands on the page.

A PORTRAIT MView sheet rotates the plot, and OCR then reads the y-axis tick
ladder BEFORE the caption: page 73 of 00340 leads with "1400". Testing only
the first line admitted 0 of that file's 412 pages, so eight CalFrac filings
— roughly 2,800 pages — reported no extractable data at all.

The obvious loosening, "any line", is wrong and was measured to be wrong:
on 00037, the file this gate was built for, it admits 14 extra pages whose
matching line is the bare word "Chemicals" — a COLUMN HEADING on the
Treatment Summary grid, 167 drawings and no curve on it. A title names its
well; a column heading does not.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calfrac_progress as cp                            # noqa: E402


class _Page(object):
    pass


class ChartPage(unittest.TestCase):
    """page_text is stubbed: what is under test is which LINE counts, not
    whether the page needed OCR to produce it."""

    def setUp(self):
        self._real = cp.ocr_labels.page_text

    def tearDown(self):
        cp.ocr_labels.page_text = self._real

    def _is_chart(self, text):
        cp.ocr_labels.page_text = lambda page: text
        return cp.is_chart_page(_Page())

    def test_landscape_title_on_the_first_line(self):
        self.assertTrue(self._is_chart(
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Surface\n"
            "Treating Pressure\n"))

    def test_rotated_sheet_leads_with_the_axis_ladder(self):
        # 00340 p73 exactly: ticks first, caption further down
        self.assertTrue(self._is_chart(
            "1400\n1200\n1000\n"
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Surface\n"))

    def test_all_three_sheet_kinds(self):
        for kind in ("Surface", "Bottom Hole", "Chemicals", "Net Pressure"):
            self.assertTrue(self._is_chart(
                f"1400\n1000\nSaguaro HZ 100/04-10-066-25W5M {kind}\n"), kind)

    def test_the_nts_well_form(self):
        self.assertTrue(self._is_chart(
            "1400\nProgress a-082-I/094-G-01 Surface\n"))
        self.assertTrue(self._is_chart(
            "1400\nSaguaro HZ Laprise 200/d-047-H/094-G-08/00 Bottom Hole\n"))

    def test_a_bare_column_heading_is_not_a_title(self):
        # 00037 p106-p118: the Treatment Summary grid. This is the whole
        # reason the rule is not "any line".
        self.assertFalse(self._is_chart(
            "Treatment Summary\nZone\nStart\nChemicals\n"))

    def test_a_heading_on_the_FIRST_line_is_still_admitted(self):
        # unchanged behaviour: the head-line test is proven over 254 pages
        # and this change is strictly additive to it
        self.assertTrue(self._is_chart("Chemicals\nsomething else\n"))

    def test_a_schematic_is_still_rejected(self):
        # 00037's tubulars diagram: read as a chart, its depth column fitted
        # as a time axis, and a 506-minute series invented from the drawing
        self.assertFalse(self._is_chart(
            "Page 1/2\nWellbore Schematic\n505.64\nZone 1\n"))

    def test_an_unreadable_page_is_not_dropped(self):
        def boom(page):
            raise RuntimeError("no")
        cp.ocr_labels.page_text = boom
        self.assertTrue(cp.is_chart_page(_Page()))


if __name__ == "__main__":
    unittest.main()
