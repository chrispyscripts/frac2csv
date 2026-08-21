"""The cheap read that rules a page out before paying to OCR it.

  python3 -m unittest tests.test_scout

lib1.detect OCRs every page that has no text of its own, at 200 dpi, and that
is the largest single cost in reading a textless filing — 3 seconds a page on
documents that run to 800. It is paid on every textless page of every
textless document, including the 136 Halliburton filings that hold no Liberty
chart at all, because reading the page is the only way to know.

The scout is a NEGATIVE filter and nothing else: it may say "no", and
anything it is unsure of pays full price exactly as before. These tests pin
that asymmetry, because the failure that matters is a chart page silently
skipped — measured at 0 of 1,254 across the corpus, and worth keeping at 0.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1


class _Page:
    """Just enough page for _worth_ocr: it only asks ocr_labels for words."""
    def __init__(self, words): self._w = words


class Scout(unittest.TestCase):
    def setUp(self):
        self._real = lib1.ocr_labels.words

    def tearDown(self):
        lib1.ocr_labels.words = self._real

    def _words(self, text):
        lib1.ocr_labels.words = lambda page, dpi=None: [
            {"text": w} for w in text.split()]

    def test_a_liberty_chart_page_is_worth_reading(self):
        self._words("Liberty Oilfield Services ARCRES HZ DOE Stage 13 "
                    "Treating Pressure MPa")
        self.assertTrue(lib1._worth_ocr(_Page(None)))

    def test_the_newer_company_name_too(self):
        self._words("Liberty Energy ARCRES Stage 4")
        self.assertTrue(lib1._worth_ocr(_Page(None)))

    def test_the_stg_spelling_of_a_stage(self):
        self._words("Liberty Energy STG 1 Treating Pressure")
        self.assertTrue(lib1._worth_ocr(_Page(None)))

    def test_a_halliburton_page_is_not(self):
        self._words("HALLIBURTON TREATMENT PLOT Treatment Interval 3 "
                    "Pump Time Slurry Rate")
        self.assertFalse(lib1._worth_ocr(_Page(None)))

    def test_a_vendor_with_no_stage_token_is_not(self):
        self._words("Liberty Oilfield Services LLC cover page")
        self.assertFalse(lib1._worth_ocr(_Page(None)))

    def test_a_stage_with_no_vendor_is_not(self):
        self._words("ARC RESOURCES Daily Completion Stage 20 Pump Down")
        self.assertFalse(lib1._worth_ocr(_Page(None)))

    def test_a_blank_page_is_not(self):
        self._words("")
        self.assertFalse(lib1._worth_ocr(_Page(None)))

    def test_an_OCR_FAILURE_never_skips_a_page(self):
        # the asymmetry that keeps this safe: broken scout, full price paid
        def boom(page, dpi=None): raise RuntimeError("tesseract died")
        lib1.ocr_labels.words = boom
        self.assertTrue(lib1._worth_ocr(_Page(None)))

    def test_the_scout_reads_at_a_lower_resolution_than_the_real_read(self):
        # 60 dpi loses the word "Liberty" off a page that has it; 100 keeps
        # it. If this is ever lowered, re-run the corpus check first.
        self.assertEqual(lib1._SCOUT_DPI, 100)
        self.assertLess(lib1._SCOUT_DPI, lib1.ocr_labels.DPI)

    def test_the_scout_is_asked_at_its_own_dpi(self):
        seen = []
        lib1.ocr_labels.words = lambda page, dpi=None: (seen.append(dpi) or [])
        lib1._worth_ocr(_Page(None))
        self.assertEqual(seen, [lib1._SCOUT_DPI])


if __name__ == "__main__":
    unittest.main()
