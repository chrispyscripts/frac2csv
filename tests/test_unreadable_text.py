"""Pages whose text layer does not say what it shows.

00745-00747 (2024, #809) embed Calibri with no ToUnicode map, so their text
is glyph numbers; 00570 (2018 Encana, #813) prints each interval's PRC plot
with no interval on it, the number on the summary sheet before it.

  python3 -m unittest tests.test_unreadable_text
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import slb                                               # noqa: E402
import step1                                             # noqa: E402

# 00745 p156's text layer, as PyMuPDF returns it
GLYPHS = ("\x12ŽŵŵĞŶƚƐ͗\n\x12ƵƐƚŽŵĞƌ͗ \x04Z\x12\x03ZĞƐŽƵƌĐĞƐ\x03>ƚĚ͘\n"
          "^ƵƌĨĂĐĞ\x03\x12ŚĂƌƚ\n/ŶƚĞƌǀĂů\x03ϭ\nϱ͕ϰϴϴ͘ϬϬ\x03ŵ\x03Ͳ\x03ϱ͕ϱϬϮ͘ϭϬ\x03ŵ\n")


class GlyphNumbers(unittest.TestCase):
    def test_calibri_glyph_numbers_are_not_text(self):
        self.assertTrue(step1._glyph_ids(GLYPHS))

    def test_a_type3_page_of_control_codes_is_not_text(self):
        self.assertTrue(step1._glyph_ids("\x00\x01\x02\x03\x04\x05\x02\x06" * 5))

    def test_ordinary_text_is_text(self):
        self.assertFalse(step1._glyph_ids(
            "Surface Chart\nInterval 1\n5,488.00 m - 5,502.10 m\nDate: 9/8/2024\n"))

    def test_a_little_accented_text_is_still_text(self):
        self.assertFalse(step1._glyph_ids("Société Générale — Montréal, Québec, été 2024"))


class Page:
    def __init__(self, doc, number, text):
        self.parent, self.number, self._text = doc, number, text

    def get_text(self):
        return self._text


SUMMARY = "Customer: Encana\nSTART TIME\nEND TIME\n12:23 AM\nInterval 1 Summary\n3:17 AM\n"


class Meta:
    def __init__(self, start, dur):
        self.start_time, self.duration_min = start, dur
        self.title, self.stage, self.warnings = "PRC Plot — Encana", "", []


class IntervalFromSummary(unittest.TestCase):
    def doc(self, summary):
        pages = []
        pages.append(Page(pages, 0, summary))
        pages.append(Page(pages, 1, "PRC Plot\n12:14 AM\n3:19 AM\n"))
        return pages

    def run_with(self, summary, start="00:14:37", dur=183.0):
        doc = self.doc(summary)
        core = (Meta(start, dur), [0, 1], {"Tr Press": [1, 2]}, {"Tr Press": "MPa"}, 0.0)
        with mock.patch.object(slb, "_extract_core", return_value=core):
            return slb._interval_from_summary(doc[1])

    def test_the_sheet_before_numbers_the_plot(self):
        meta, _s, data, _u = self.run_with(SUMMARY)
        self.assertEqual(meta.stage, "1")
        self.assertIn("Interval 1", meta.title)
        self.assertIn("Tr Press", data)

    def test_a_sheet_whose_times_are_off_the_axis_does_not(self):
        self.assertIsNone(self.run_with(SUMMARY, start="17:10:26"))

    def test_a_whole_job_plot_is_still_not_a_stage(self):
        self.assertIsNone(self.run_with(SUMMARY, dur=31 * 60.0))

    def test_no_sheet_no_number(self):
        self.assertIsNone(self.run_with("Daily Ops\nnothing here\n"))


class OcrdChartPage(unittest.TestCase):
    """00347 p99 (#811): a 2017 page in an unreadable font, OCR'd. Its title
    reads "Interval Summary" over "Treatment", the number lost, and no
    "LSD:" line came through: the page was passed over as no chart."""

    class P:
        def get_text(self):
            return GLYPHS

    OCR = ("STEP Energy Services Interval Summary\nTreatment\n"
           "2,188.86 m - 2,188.96 m\n60\n18\n600\n1200\n")

    def detect(self, text, images=2):
        with mock.patch.object(step1, "_big_images", return_value=[object()] * images), \
                mock.patch.object(step1, "_page_text", return_value=text):
            return step1._detect_new(self.P())

    def test_the_summary_header_over_two_charts_is_a_chart_page(self):
        self.assertTrue(self.detect(self.OCR))

    def test_one_picture_is_not_enough(self):
        self.assertFalse(self.detect(self.OCR, images=1))

    def test_another_vendors_page_is_not(self):
        self.assertFalse(self.detect("Interval Summary\nTreatment\n"))


if __name__ == "__main__":
    unittest.main()
