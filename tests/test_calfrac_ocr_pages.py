"""CalFrac multi-zone pages with no text layer (00228, 00234: 094-H Montney).

Their titles, captions and legends are outlined glyphs, so every word comes
from OCR, in OCR's order — and three readers keyed on the FIRST line or on a
clean caption:

  * calfrac_progress.detect: the Bottom Hole sheet's first OCR line is the
    "1000" of a tick ladder, so it was not taken for a zone page, never
    borrowed its Surface twin's cuts, and went out WHOLE under the last
    zone's number (00228's 500-minute "21", 00234's 320-minute "18").
  * calfrac_progress.zone_range: 00228 p73's caption "Zone 1-9" OCRs as
    "Zone | - 9"; the page went out as one unnumbered 640-minute chart and
    zones 1-9 were missing.
  * frac_core.is_chemicals: 00234 p84 OCRs its additive legend before its
    title, was read as a treatment chart and filed as a second zone 18.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calfrac_progress as cp                            # noqa: E402
import frac_core as fc                                   # noqa: E402


class _Page(object):
    pass


class _Stub(unittest.TestCase):
    def setUp(self):
        self._text = cp.ocr_labels.page_text
        self._garbled = cp.ocr_labels.garbled

    def tearDown(self):
        cp.ocr_labels.page_text = self._text
        cp.ocr_labels.garbled = self._garbled

    def _set(self, text, garbled=True):
        cp.ocr_labels.page_text = lambda page: text
        cp.ocr_labels.garbled = lambda page: garbled


# 00228 p81, as OCR returns it (abridged)
BH_P81 = ("1000\n800\n600\n400\n300\n"
          "— Master Conc @ Wellhead (kg/m?)\n"
          "Chinook 200/d-E083-F/094-H-03/00 Bottom Hole\n"
          "400\nTime (min)\n200\n—Treating Pressure (MPa)\n")
# 00234 p84
CHEM_P84 = ("—DWP-621 Friction Reducer Conc. (L/m?)\n"
            "—DWP-913 Clacy Control Conc. (L/m?)\n"
            "4\n320\n—DWP-944 Biocide Conc. (L/m?)\n"
            "Chinook 200/d-F083-F/094-H-03/00 Chemicals\n"
            "240\nTime (min)\n")
# 00228 p73
SURF_P73 = ("1000\n400\n800\n300\n"
            "Chinook 200/d-E083-F/094-H-03/00 Surface\n"
            "Time (min)\nZone | - 9\n320\n")


class BottomHoleSheet(_Stub):
    def test_a_title_below_the_tick_ladder_is_a_zone_page(self):
        self._set(BH_P81)
        self.assertTrue(cp.detect(_Page()))

    def test_a_bare_column_heading_is_not(self):
        self._set("1000\nChemicals\n800\n")
        self.assertFalse(cp.detect(_Page()))


class OcrCaption(_Stub):
    def test_a_bar_for_the_one(self):
        self._set(SURF_P73)
        self.assertEqual(cp.zone_range(_Page()), (1, 9))

    def test_letters_for_the_one(self):
        for cap in ("Zones l-6", "Zone I-3"):
            self._set(f"Chinook Surface\n{cap}\n")
            self.assertEqual(cp.zone_range(_Page())[0], 1, cap)

    def test_a_bar_is_not_read_as_a_one_anywhere_else(self):
        self._set("Chinook Surface\nZone | 9\n")
        self.assertIsNone(cp.zone_range(_Page()))
        self.assertEqual(cp._ocr_ones("Pressure | - 9"), "Pressure | - 9")


class ChemicalsSheet(_Stub):
    def test_an_ocr_title_below_the_legend(self):
        self._set(CHEM_P84, garbled=True)
        self.assertTrue(fc.is_chemicals(_Page()))

    def test_a_treatment_sheet_is_not_one(self):
        self._set(BH_P81, garbled=True)
        self.assertFalse(fc.is_chemicals(_Page()))

    def test_a_page_with_a_text_layer_still_reads_its_first_line_only(self):
        # a readable page is not second-guessed: its title IS line one
        self._set("Tourmaline 102/08-07 Surface\nTourmaline Chemicals\n",
                  garbled=False)
        self.assertFalse(fc.is_chemicals(_Page()))


class RedRateLadder(unittest.TestCase):
    """The rate axis full scale off its red tick labels (00228, 00234)."""

    def setUp(self):
        self._ladder = fc.ocr_labels.red_tick_ladder

    def tearDown(self):
        fc.ocr_labels.red_tick_ladder = self._ladder

    def _scale(self, pts):
        import fitz
        fc.ocr_labels.red_tick_ladder = lambda page, clip: pts

        class P(object):
            rect = fitz.Rect(0, 0, 595, 842)
        return fc._red_rate_scale(P(), fitz.Rect(94.4, 121.1, 547.8, 745.8))

    def test_the_labels_sit_off_their_ticks_and_the_top_still_reads(self):
        # 00234 p81, as read: centred 7.8 pt short of each tick
        self.assertEqual(self._scale([(86.6, 10), (177.3, 8), (268.0, 6),
                                      (358.6, 4), (449.3, 2), (540.0, 0)]),
                         10.0)

    def test_a_missing_top_label_is_recovered_from_the_line(self):
        self.assertEqual(self._scale([(177.3, 8), (268.0, 6), (358.6, 4),
                                      (449.3, 2), (540.0, 0)]), 10.0)

    def test_a_bottom_hole_ladder_of_threes(self):
        self.assertEqual(self._scale([(86.6, 15), (177.3, 12), (268.0, 9),
                                      (358.6, 6), (449.3, 3), (540.0, 0)]),
                         15.0)

    def test_too_few_labels_is_no_scale(self):
        self.assertIsNone(self._scale([(177.3, 8), (268.0, 6), (358.6, 4)]))


class CutOffRange(_Stub):
    """00261 p84 captions its plot "Zones 1 -" (the box cut the end off)."""

    def _run(self, caption, next_first):
        import pipeline
        pages = {84: "Tourmaline Hz Sunset Surface\n   " + caption + "\n",
                 89: "Tourmaline Hz Sunset Surface\nZones 2 - 20\n"}

        class Doc(object):
            def __getitem__(self, i):
                return pages.get(i + 1, "")
        cp.ocr_labels.page_text = lambda page: page
        cut = {"source": "CalFrac chart", "page": 84,
               "meta": {"stage": None, "mv": " Surface",
                        "warnings": ["stage/zone not found"]}}
        nxt = {"source": "CalFrac chart", "page": 89,
               "meta": {"stage": f"{next_first} Surface", "zone_span": 19}}
        notes = []
        pipeline._calfrac_cut_off_ranges(Doc(), [cut, nxt], notes)
        return cut, notes

    def test_read_as_one_zone_when_the_next_range_opens_after_it(self):
        cut, notes = self._run("Zones 1 -", 2)
        self.assertEqual(cut["meta"]["stage"], "1 Surface")
        self.assertEqual(cut["meta"]["warnings"], [])
        self.assertIn("p89", notes[0])

    def test_left_alone_when_the_next_range_does_not_follow_on(self):
        cut, _ = self._run("Zones 1 -", 5)
        self.assertIsNone(cut["meta"]["stage"])

    def test_a_whole_range_is_not_cut_off(self):
        self._set("Zones 1 - 4\n")
        self.assertIsNone(cp.cut_off_range(_Page()))
        self._set("   Zones 1 -\n")
        self.assertEqual(cp.cut_off_range(_Page()), 1)


class OutlinedSheet(unittest.TestCase):
    """The summary sheets of 00228/00234 are outlined glyphs too. OCR reads
    them; these are the rows it hands zone_times and sheet_job_date, with the
    noise it actually produced."""

    # 00234 p80, as OCR rows: a clipped "Start Tim", a comma after a time
    P80 = [(82.0, [(13.0, "Customer:"), (87.0, "Chinook Energy Inc."),
                   (345.0, "Job Date:"), (376.0, "Feb 2, 2017")]),
           (360.0, [(60.0, "ZONE #:"), (102.0, "11"), (140.0, "12"),
                    (178.0, "13")]),
           (392.0, [(13.0, "Start Tim"), (98.0, "13:55"), (136.0, "14:39"),
                    (174.0, "15:16")]),
           (400.0, [(13.0, "Stop Time:"), (98.0, "14:39"), (136.0, "15:16"),
                    (174.0, "15:50")])]

    def test_times_off_ocr_rows(self):
        self.assertEqual(cp.zone_times(None, self.P80), {
            11: {"start": "13:55", "stop": "14:39"},
            12: {"start": "14:39", "stop": "15:16"},
            13: {"start": "15:16", "stop": "15:50"}})

    def test_job_date_off_ocr_rows(self):
        self.assertEqual(cp.sheet_job_date(None, rows=self.P80), "2017-02-02")

    def test_a_job_date_run_into_its_label(self):
        # 00228 p79
        rows = [(82.0, [(7.0, "Customer:"),
                        (345.0, "Job Date: : Jan 28, 2017")])]
        self.assertEqual(cp.sheet_job_date(None, rows=rows), "2017-01-28")

    def test_a_dropped_digit_in_the_zone_row(self):
        # 00228 p78 reads "1 12 13 ... 20"
        cells = [(59.0, "ZONE #:"), (101.0, "1"), (139.0, "12"),
                 (177.0, "13"), (215.0, "14")]
        self.assertEqual([t for _x, t in cp._ocr_zone_header(cells)],
                         ["ZONE #:", "11", "12", "13", "14"])

    def test_a_zone_row_that_agrees_is_left_alone(self):
        cells = [(59.0, "ZONE #:"), (101.0, "21"), (139.0, "22")]
        self.assertEqual(cp._ocr_zone_header(cells), cells)
        # a break the neighbours do not agree on is not "repaired"
        cells = [(59.0, "ZONE #:"), (101.0, "1"), (139.0, "12")]
        self.assertEqual(cp._ocr_zone_header(cells), cells)


if __name__ == "__main__":
    unittest.main()
