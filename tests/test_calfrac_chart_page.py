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


class FooterDate(unittest.TestCase):
    """The MView footer is the ONLY date on a Bottom Hole sheet.

    The Surface sheet prints "March 1, 2022" as its own line and frac_core
    reads that; the Bottom Hole sheet prints no such line, so the footer is
    all it has. OCR eats the leading "M" of "MView" often enough to matter —
    p74 of 00340 reads "View - Annular Ignition ... - 3/1/2022" and p73 reads
    "- Annular Ianition ... - 3/1/2022" — and an anchored ^MView then cost
    that sheet its date outright.

    Measured before relaxing: over all 366 pages of 00037 the loose form
    agrees with the anchored one on all 248 pages the anchored one matches,
    disagrees on none, and finds nothing extra.
    """

    def setUp(self):
        self._real = cp.ocr_labels.page_text

    def tearDown(self):
        cp.ocr_labels.page_text = self._real

    def _date(self, text):
        cp.ocr_labels.page_text = lambda page: text
        return cp.job_date(_Page())

    def test_the_anchored_footer(self):
        self.assertEqual(
            self._date("MView - CWS-600 N2 Casing Clancy - 3/10/2015"),
            "2015-03-10")

    def test_the_leading_M_eaten_by_ocr(self):
        self.assertEqual(
            self._date("View - Annular Ignition x.x Master Raw Template "
                       "-A 100 04-10 - 3/1/2022"), "2022-03-01")

    def test_the_whole_word_eaten_by_ocr(self):
        self.assertEqual(
            self._date("- Annular Ianition x.x Master Raw Template "
                       "-A 100 04-10 - 3/1/2022"), "2022-03-01")

    def test_the_footer_is_the_LAST_such_line(self):
        self.assertEqual(
            self._date("Some header - 1/2/2020\n"
                       "MView - Template - 3/4/2022\n"), "2022-03-04")

    def test_a_page_with_no_footer_date(self):
        self.assertIsNone(self._date("Zone: 1/85\nMarch 1, 2022\n"))

    def test_an_impossible_month_is_refused(self):
        self.assertIsNone(self._date("MView - Template - 13/40/2022"))

    def test_read_through_ocr_so_a_textless_page_works(self):
        # the whole reason 17 of 41 charts were dated on 00339: this read the
        # raw text layer, and these filings have none
        seen = []
        cp.ocr_labels.page_text = lambda page: seen.append(page) or \
            "View - Template - 3/1/2022"
        self.assertEqual(cp.job_date(_Page()), "2022-03-01")
        self.assertEqual(len(seen), 1)
