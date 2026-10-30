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


class _Outlined(object):
    """A page with no text layer at all, as 00228/00234's sheets are."""
    number = 73
    rotation = 0

    def __init__(self, text=""):
        self._text = text

    def get_text(self, *a):
        return self._text


def _string(rect, text, rgb=(0.0, 0.0, 0.0), conf=96.0, d=(0.0, -1.0), n=None):
    import fitz
    return {"text": text, "rect": fitz.Rect(rect), "dir": d,
            "n": n or len(text), "color": rgb, "conf": conf}


BLUE, BLACK, RED = (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
TEAL, PURPLE = (0.0, 0.5, 0.5), (0.5, 0.0, 0.5)

# 00228 p74, the Bottom Hole sheet of zones 1-9: its legend keys...
P74_KEYS = [(BLUE, (48.48, 715.08, 48.48, 742.32)),
            (BLACK, (65.40, 715.08, 65.40, 742.32)),
            (RED, (48.48, 300.00, 48.48, 327.24)),
            (TEAL, (65.40, 300.00, 65.40, 327.24)),
            (PURPLE, (82.20, 300.00, 82.20, 327.24))]
# ...its labels as outline_spans reads them (ink boxes, page space)...
P74_DRAWN = [_string((43.2, 561.8, 57.0, 714.4), "Treating Pressure (MPa)", BLUE),
             _string((60.0, 538.1, 73.8, 714.5), "Bottom Hole Pressure (MPa)"),
             _string((43.2, 128.9, 57.0, 299.4), "Rate @ Formation (m3/min)", RED, 82),
             _string((60.0, 92.2, 73.9, 299.4), "Master Conc @ Wellhead (kg/m3)",
                     TEAL, 59),
             _string((76.9, 87.0, 90.8, 299.4), "Master Conc @ Formation (kg/m3)",
                     PURPLE, 25)]
# ...and the lines the whole-page OCR made of it: the title swallowed both
# legend columns, and its box covers the blue and black keys and abuts them
P74_OCR = [((-5.3, 149.8, 67.6, 712.4),
            "Chinook 200/d-E083-F/094-H-03/00 Bottom Hole"),
           ((40.8, 611.6, 76.9, 742.0), "Bot tom Hole Pre"),
           ((33.9, 194.4, 77.8, 326.9), "Rate @F ormatio")]


class OutlinedLegend(unittest.TestCase):
    """00228 p74 and 00234 p77 failed "no treatment channel in the page
    legend (Chinook … Bottom Hole)": their keys were labelled with the OCR'd
    title. The labels are read as the strings the page drew."""

    def setUp(self):
        import fitz
        self._saved = (fc._legend_keys, fc.ocr_labels.garbled,
                       fc.ocr_labels.text_spans, fc.ocr_labels.outline_spans)
        fc._legend_keys = lambda page: [(rgb, fitz.Rect(r), False)
                                        for rgb, r in P74_KEYS]
        fc.ocr_labels.garbled = lambda page: True
        fc.ocr_labels.text_spans = lambda page: P74_OCR
        fc.ocr_labels.outline_spans = lambda page, accept=None: P74_DRAWN

    def tearDown(self):
        (fc._legend_keys, fc.ocr_labels.garbled,
         fc.ocr_labels.text_spans, fc.ocr_labels.outline_spans) = self._saved

    def test_every_key_takes_the_label_drawn_beside_it(self):
        mapping, blocks = fc.detect_legend(_Outlined())
        self.assertEqual({rgb: col for rgb, (col, _k) in mapping.items()},
                         {BLUE: "Tr Press", RED: "Slurry Rate",
                          TEAL: "WH Prop Conc", PURPLE: "BH Prop Conc"})
        # the black Bottom Hole Pressure is known, and deliberately left out
        self.assertIn((BLACK, "Bottom Hole Pressure (MPa)", None),
                      [e for b in blocks for e in b])

    def test_the_ocr_lines_alone_name_no_channel(self):
        # what the sheet read as before: the title on both pressure keys
        fc.ocr_labels.outline_spans = lambda page, accept=None: []
        mapping, blocks = fc.detect_legend(_Outlined())
        self.assertEqual(mapping, {})
        self.assertEqual({t for b in blocks for _r, t, _c in b},
                         {"Chinook 200/d-E083-F/094-H-03/00 Bottom Hole"})

    def test_a_type3_page_is_not_asked(self):
        # garbled, but its labels are text (00339): the OCR lines stand
        def refuse(page, accept=None):
            raise AssertionError("outline_spans asked of a page with text")
        fc.ocr_labels.outline_spans = refuse
        fc.detect_legend(_Outlined(text="\x01\x02\x03 \x04\x05"))


class OutlinedNumbers(unittest.TestCase):
    """The tick labels of an outlined sheet, read off its drawn strings."""

    # 00228 p74's first tick: "15" red and "500" teal, and the pressure "100"
    P74 = [_string((88.3, 95.9, 94.6, 104.2), "15", RED, 97),
           _string((97.8, 91.2, 104.2, 104.8), "500", TEAL, 97),
           _string((88.3, 750.2, 94.6, 763.1), "100", BLACK, 97),
           _string((395.5, 49.4, 406.4, 63.1), "3", BLACK, 54, n=1),
           _string((43.2, 561.8, 57.0, 714.4), "Treating Pressure (MPa)", BLUE)]

    def setUp(self):
        self._saved = (fc.ocr_labels.outline_spans, fc.ocr_labels.garbled,
                       fc.ocr_labels.numeric_spans)
        fc.ocr_labels.outline_spans = lambda page, accept=None: self.P74
        fc.ocr_labels.garbled = lambda page: True
        fc.ocr_labels.numeric_spans = lambda page: [((0, 0, 1, 1), 7.0)]

    def tearDown(self):
        (fc.ocr_labels.outline_spans, fc.ocr_labels.garbled,
         fc.ocr_labels.numeric_spans) = self._saved

    def test_numbers_only_and_sure_ones(self):
        got = fc.ocr_labels.outline_numeric_spans(_Outlined())
        self.assertEqual([v for _b, v in got], [15.0, 500.0, 100.0])

    def test_one_ticks_labels_abut_as_line_boxes(self):
        # 3.2 pt of white between the two inks; _axis_columns joins a run
        # whose boxes come within _TICK_GAP (1.5 pt)
        (b15, _), (b500, _) = fc.ocr_labels.outline_numeric_spans(_Outlined())[:2]
        self.assertLess(b500[0] - b15[2], fc._TICK_GAP)
        self.assertEqual((b15[1], b15[3]), (95.9, 104.2))   # along the run: as drawn

    def test_an_outlined_page_reads_its_drawn_numbers(self):
        self.assertEqual([v for _b, v in fc._numeric_spans(_Outlined())],
                         [15.0, 500.0, 100.0])

    def test_the_page_pass_when_nothing_drawn_is_a_number(self):
        fc.ocr_labels.outline_spans = lambda page, accept=None: []
        self.assertEqual(fc._numeric_spans(_Outlined()), [((0, 0, 1, 1), 7.0)])

    def test_a_type3_page_keeps_the_page_pass(self):
        self.assertEqual(fc._numeric_spans(_Outlined(text="\x01\x02\x03")),
                         [((0, 0, 1, 1), 7.0)])


class OutlinedOrientation(unittest.TestCase):
    """00234 p77's OCR reads "Time nim", so the axis title said nothing and
    the sheet fell back to /Rotate 0 — "x" — though it is drawn sideways."""

    def setUp(self):
        self._saved = (fc.ocr_labels.outline_spans, fc.ocr_labels.garbled,
                       fc.ocr_labels.text_spans)
        fc.ocr_labels.garbled = lambda page: True
        fc.ocr_labels.text_spans = lambda page: [((509.0, 365.8, 608.8, 496.1),
                                                  "Time nim")]

    def tearDown(self):
        (fc.ocr_labels.outline_spans, fc.ocr_labels.garbled,
         fc.ocr_labels.text_spans) = self._saved

    def _orient(self, strings, text=""):
        import fitz
        fc.ocr_labels.outline_spans = lambda page, accept=None: strings
        return fc._orientation(_Outlined(text),
                               fitz.Rect(94.4, 116.3, 547.8, 745.8))

    def test_labels_running_along_y(self):
        self.assertEqual(self._orient(P74_DRAWN), "y")

    def test_labels_running_along_x(self):
        self.assertEqual(self._orient([_string((90, 40, 300, 50), "Treating Pressure",
                                               d=(1.0, 0.0))]), "x")

    def test_single_glyphs_say_nothing(self):
        # a lone "0" has no direction of its own (outline_spans calls it
        # (1, 0)); with nothing else drawn, /Rotate decides as before
        self.assertEqual(self._orient([_string((90, 40, 96, 48), "0", d=(1.0, 0.0),
                                               n=1)]), "x")

    def test_the_axis_title_still_comes_first(self):
        fc.ocr_labels.text_spans = lambda page: [((540.0, 365.8, 604.8, 496.1),
                                                  "Time (min)")]
        self.assertEqual(self._orient([_string((90, 40, 300, 50), "Treating",
                                               d=(1.0, 0.0))]), "y")


if __name__ == "__main__":
    unittest.main()
