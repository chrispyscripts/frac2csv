"""A file that is nothing but pictures should say what it IS.

#678 flagged nine files. Three of them — 00426, 00428, 00429 — are 124-page
runs of Petrosight "Daily Initial Completions Report" sheets: daily ops
paperwork, well shut in, no treatment chart anywhere in them. The reader's
answer was two guesses at once — "Reading it needs OCR, and it may be a
daily report that holds no treatment charts to begin with" — which leaves
nothing to do but flag the file again.

Tesseract ships inside the Windows build, so the banner can simply be read.
All three now come back "Daily Initial Completions Report - <date> - Day #N".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline


class Daily(unittest.TestCase):

    def test_the_banners_these_files_actually_print(self):
        for t in ("Daily Initial Completions Report - 2020-09-30 - Day #28",
                  "Daily Initial Completions Report - 2020-10-01 - Day #30",
                  "Daily Drilling Report",
                  "Morning Report",
                  "Report Date 2020-10-01"):
            self.assertTrue(pipeline._is_daily(t), t)

    def test_a_treatment_sheet_is_not_a_daily_report(self):
        for t in ("Treatment Plot", "STAGE INFORMATION",
                  "PRESSURES, RATES, AND CONCENTRATIONS",
                  "CONTINUOUS SCHEDULE", "COMPLETION / WORKOVER", ""):
            self.assertFalse(pipeline._is_daily(t), t)


class Spread(unittest.TestCase):
    """Which pages get OCR'd — a cover sheet must not be the only one read."""

    def test_the_first_page_is_always_one_of_them(self):
        self.assertEqual(pipeline._spread(124, 4)[0], 0)

    def test_they_reach_the_end(self):
        self.assertEqual(pipeline._spread(124, 4)[-1], 123)

    def test_four_pages_spread_through_the_file(self):
        self.assertEqual(pipeline._spread(124, 4), [0, 41, 82, 123])

    def test_a_short_file_is_taken_whole(self):
        self.assertEqual(pipeline._spread(3, 4), [0, 1, 2])


class Pick(unittest.TestCase):
    """_scanned_kind prefers the body's banner over the cover sheet's."""

    class FakeDoc:
        def __init__(self, texts):
            self.texts = texts

        def __getitem__(self, i):
            return self.texts[i]

    def kind(self, texts, monkey=True):
        import ocr_labels
        doc = self.FakeDoc(texts)
        old_av, old_tx = ocr_labels.available, ocr_labels.page_text
        ocr_labels.available = lambda: True
        ocr_labels.page_text = lambda page: page
        try:
            return pipeline._scanned_kind(doc, len(texts))
        finally:
            ocr_labels.available, ocr_labels.page_text = old_av, old_tx

    def test_the_cover_sheet_loses_to_the_body(self):
        # 00426 exactly: the cover names the binder, the body names the pages
        got = self.kind(["COMPLETION / WORKOVER",
                         "Daily Initial Completions Report - 2020-09-30 - Day #28",
                         "Daily Initial Completions Report - 2020-10-01 - Day #29",
                         "Daily Initial Completions Report - 2020-10-02 - Day #30"])
        self.assertTrue(pipeline._is_daily(got))
        self.assertIn("Daily Initial Completions Report", got)

    def test_short_and_wordless_lines_are_not_banners(self):
        got = self.kind(["12/34", "-", "x", "Treatment Report Summary Page"])
        self.assertEqual(got, "Treatment Report Summary Page")

    def test_nothing_readable_says_nothing(self):
        self.assertEqual(self.kind(["", "  ", "1234 5678", "--"]), "")

    def test_without_tesseract_it_does_not_guess(self):
        import ocr_labels
        old = ocr_labels.available
        ocr_labels.available = lambda: False
        try:
            self.assertEqual(pipeline._scanned_kind(self.FakeDoc(["Daily Report"]), 1), "")
        finally:
            ocr_labels.available = old


if __name__ == "__main__":
    unittest.main()
