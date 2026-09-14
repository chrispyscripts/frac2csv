"""The BJ Totals table is read whether or not the book has charts (#647).

  python3 -m unittest tests.test_bj_totals_gate
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bj_summary                                          # noqa: E402


class _Page(object):
    def __init__(self, text):
        self._text = text

    def get_text(self, *a, **k):
        return self._text


class _Doc(object):
    def __init__(self, *texts):
        self._pages = [_Page(t) for t in texts]
        self.page_count = len(self._pages)

    def __getitem__(self, i):
        return self._pages[i]


TOTALS = "Totals\nUOM\nInterval #\nStart time\nBreakdown\nPressure\n1\n1/29/2025 2:33\n"


class DetectDocument(unittest.TestCase):

    def test_a_book_with_the_totals_page_is_detected(self):
        self.assertTrue(bj_summary.detect_document(_Doc("Daily report\n", TOTALS)))

    def test_a_book_without_it_is_not(self):
        self.assertFalse(bj_summary.detect_document(_Doc("Daily report\n", "Schematic\n")))

    def test_the_word_totals_alone_is_not_the_table(self):
        self.assertFalse(bj_summary.detect_document(_Doc("Totals\nfluid 58 m3\n")))


if __name__ == "__main__":
    unittest.main()
