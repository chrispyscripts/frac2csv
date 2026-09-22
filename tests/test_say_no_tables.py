"""An empty Tables tab has to say which half of the file it looked at.

_say_no_tables named the pages that carry TEXT and stopped there. That is the
right answer for #691's Liberty filing, where every other page is a chart the
reader read. It is the wrong half of two of the files behind this batch:

  * 00218 (#698) — 379 pages. Pages 1-145 are Peloton "Regulatory_Daily
    Completion and Workover" sheets with a text layer; 146-379 are the
    Halliburton IFS report, SCANNED. p197 is its "9.1 Stage Summary", six
    pump stages with start time, treating pressure, rates, volumes and
    proppant mass, and get_text("words") on it returns nothing.
  * 00453 (#705) — 346 pages, same shape: 147 Peloton daily pages, then a
    Halliburton "WELL STIMULATION REPORT" that is pictures from p148 on.
    p200 is a 22-row ACTUAL DESIGN grid, printed, and unreadable.

So the tables ARE there. Told only that ~140 pages carry text, the reader goes
looking through the Peloton daily reports, where the treatment tables never
were. The note now counts the pages that carry neither text nor a chart, and
says what that means, without claiming to know what is drawn on them.

A page that DID produce a chart stays uncounted — otherwise every Liberty
filing would be told its charts might be hiding tables.

Run: python3 -m pytest tests/test_say_no_tables.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                          # noqa: E402


class _Page(object):
    def __init__(self, words, images):
        self._words = words
        self._images = images

    def get_text(self, kind="text", *a, **k):
        return ["w"] * self._words if kind == "words" else "w " * self._words

    def get_images(self, *a, **k):
        return [("img",)] if self._images else []


class _Doc(object):
    def __init__(self, pages):
        self._pages = pages
        self.page_count = len(pages)

    def __getitem__(self, i):
        return self._pages[i]


def _text_page():
    return _Page(400, True)       # a Peloton daily sheet


def _picture_page():
    return _Page(0, True)         # a scanned page, no text layer


def _note(pages, charted_pages):
    """The note _say_no_tables leaves for a filing that produced charts on
    `charted_pages` (1-based) and no table at all."""
    results = [{"type": "series", "page": p} for p in charted_pages]
    notes = []
    pipeline._say_no_tables(_Doc(pages), results, notes, len(pages))
    return notes[0] if notes else ""


class TheScannedHalf(unittest.TestCase):
    """00218's measured shape. Counted off the file: 137 pages carry 120+
    words, 8 carry a handful, 234 carry none at all, and 233 of those 234
    hold an image. extract_document read 9 IFS charts off the scanned half,
    so 224 pictures produced neither text nor a chart."""

    PAGES = ([_text_page()] * 137 + [_Page(60, True)] * 8
             + [_picture_page()] * 233 + [_Page(0, False)])
    CHARTED = list(range(146, 155))            # the 9 charts that did read

    def test_it_still_counts_the_text_pages(self):
        self.assertIn("137 of 379 pages", _note(self.PAGES, self.CHARTED))

    def test_it_names_the_pages_nothing_was_read_from(self):
        """233 pictures less the 9 that produced a chart. The 8 pages with a
        little text and the one blank are neither, and are not counted."""
        self.assertIn("A further 224 of the 379", _note(self.PAGES,
                                                        self.CHARTED))

    def test_it_says_why_those_pages_are_unreadable(self):
        self.assertIn("without OCR", _note(self.PAGES, self.CHARTED))

    def test_it_does_not_promise_the_export_is_complete(self):
        """The old note's reassurance — "Nothing is missing from the export"
        — is a claim about pages nobody read. It must not be made here."""
        self.assertNotIn("Nothing is missing", _note(self.PAGES, self.CHARTED))


class TwoPagesIsAPlaceToLook(unittest.TestCase):
    """00915 (#706), a 151-page Liberty filing. Exactly two pages carry text:
    p1 is the BC OGC cover form, and p103 is a "Frac Fluid and Additive
    Treatment Report" spreadsheet — 22 stage rows, each with its interval
    depths, breakdown/average/max pressure, rates, fluid and proppant totals.
    It is a real table and no Liberty parser reads this layout, so "2 of 151
    pages" was true and useless. Naming them puts the reader on p103."""

    PAGES = ([_text_page()] + [_picture_page()] * 101 + [_text_page()]
             + [_picture_page()] * 48)
    CHARTED = list(range(2, 103)) + list(range(104, 152))

    def test_it_names_the_two_pages(self):
        self.assertIn("(pages 1, 103)", _note(self.PAGES, self.CHARTED))

    def test_the_charts_it_set_aside_are_not_called_unread(self):
        """The real file exports 24 charts off 144 rasterised pages and sets
        24 chemical-only ones aside, so most of those pages end up with
        nothing exported from them. The note may say that; it may not say the
        reader found nothing there, which is not true of the ones it read."""
        note = _note(self.PAGES, list(range(2, 26)))
        self.assertIn("no chart was exported from them", note)
        self.assertNotIn("produced no chart", note)

    def test_a_filing_with_too_many_to_name_still_counts_them(self):
        """00218's 137 text pages are a list nobody reads."""
        note = _note([_text_page()] * 137 + [_picture_page()] * 242,
                     list(range(138, 147)))
        self.assertIn("137 of 379 pages", note)
        self.assertNotIn("(pages", note)


class TheFilingThatReallyHasNoTable(unittest.TestCase):
    """#691's shape, which the note was written for: one cover form, and
    every other page a chart the reader read. Unchanged."""

    PAGES = [_text_page()] + [_picture_page()] * 251
    CHARTED = list(range(2, 253))

    def test_a_charted_page_is_not_counted_as_unread(self):
        self.assertNotIn("A further", _note(self.PAGES, self.CHARTED))

    def test_the_reassurance_survives(self):
        note = _note([_picture_page()] * 252, list(range(1, 253)))
        self.assertIn("they are charts", note)
        self.assertIn("Nothing is missing from the export", note)


class WhenItSaysNothing(unittest.TestCase):

    def test_a_filing_that_produced_a_table_is_left_alone(self):
        notes = []
        pipeline._say_no_tables(
            _Doc([_text_page()]),
            [{"type": "series", "page": 1}, {"type": "table", "rows": [[1]]}],
            notes, 1)
        self.assertEqual(notes, [])

    def test_a_filing_with_no_charts_is_left_to_why_nothing(self):
        notes = []
        pipeline._say_no_tables(_Doc([_text_page()]), [], notes, 1)
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
