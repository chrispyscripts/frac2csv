"""BJ-1 detection: the title line, not three marks scattered over a page.

The last page of 00440, 00441, 00442, 00443 and 00461 is a spreadsheet
printed to PDF — 1,545 lines, column letters A..BW down the side. Somewhere
in it is a well id, somewhere the word "Stage", somewhere a "Mon-DD HH:MM",
so a whole-page test for all three fired on it. bj1 then failed with "time
labels not found" and that failure was the ONLY thing those five files ever
produced.

Measured before the change: of the 11 corpus files that yield BJ charts, all
878 detected pages carry a line holding both the well id and "Stage"; none is
lost. All five spreadsheet pages lose it.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bj1                                               # noqa: E402


class _Page(object):
    def __init__(self, text):
        self._text = text

    def get_text(self, *a, **k):
        return self._text


# 00633's chart page: axis labels down the side, the title in the middle
CHART = """Apr-13 22:15
Apr-13 22:30
Apr-13 22:45
100-12-27-079-16W6 - Well D - Stage 01
Treating Pressure
Slurry Rate
"""

# 01215's NTS-named filing, and the slash separator
CHART_NTS = """Nov-08 06:00
Nov-08 06:15
200/C-022-C-094-G-01 - Well A - Stage 12
"""

# what the five suspects' last page looks like: the marks are all present
# and no single line holds the title
SPREADSHEET = """1
2
BI
BJ
BK
Service Company
Liberty Oilfield Services
100/03-26-062-04W6
Stage
Apr-13 22:15
Total Pump Time
"""


class BJDetect(unittest.TestCase):
    def test_a_real_chart_title_fires(self):
        self.assertTrue(bj1.detect(_Page(CHART)))

    def test_the_nts_and_slash_forms_still_fire(self):
        self.assertTrue(bj1.detect(_Page(CHART_NTS)))

    def test_a_spreadsheet_dump_does_not(self):
        self.assertFalse(bj1.detect(_Page(SPREADSHEET)))

    def test_a_title_with_no_time_axis_does_not(self):
        # the table of contents names intervals and wells and plots nothing
        self.assertFalse(bj1.detect(
            _Page("100-12-27-079-16W6 - Well D - Stage 01\nStage 02\n")))

    def test_a_time_axis_with_no_title_does_not(self):
        self.assertFalse(bj1.detect(_Page("Apr-13 22:15\nApr-13 22:30\n")))

    def test_the_hyphen_separator_is_not_required_to_be_a_slash(self):
        # #633: matching only "100/12-27-..." dropped all 10 of its charts
        for wid in ("100-12-27-079-16W6", "100/12-27-079-16W6"):
            self.assertTrue(
                bj1.detect(_Page(f"Apr-13 22:15\n{wid} - Well D - Stage 01\n")),
                wid)

    def test_a_two_digit_township_is_the_same_well(self):
        # #644: 00634 titles "102-09-28-79-16W6" where its tables say
        # 102/09-28-079-16W6/00; four chart pages were skipped as schematics
        self.assertTrue(bj1.detect(
            _Page("Apr-13 19:30\n102-09-28-79-16W6 - Well E - Stage 01\n")))


class ParseTitle(unittest.TestCase):

    def test_township_is_padded_back_to_three_digits(self):
        self.assertEqual(bj1.parse_title("102-09-28-79-16W6 - Well E - Stage 01"),
                         ("102092807916W600", "1"))
        self.assertEqual(bj1.parse_title("100-12-27-079-16W6 - Well D - Stage 03"),
                         ("100122707916W600", "3"))

    def test_nts_names_still_parse(self):
        self.assertEqual(bj1.parse_title("200/C-022-C-094-G-01 - Well A - Stage 12"),
                         ("200C022C094G0100", "12"))

    def test_nothing_is_nothing(self):
        self.assertEqual(bj1.parse_title("Service Company\nStage\n"), ("", ""))


class Unnumbered(unittest.TestCase):

    def test_a_plug_erosion_chart_is_named_not_read(self):
        # 00634 p72: a well, a time axis, no stage
        self.assertEqual(
            bj1.unnumbered_title(_Page("Apr-13 19:30\n102-09-28-79-16W6 - Well E - plug erosion\n")),
            "102-09-28-79-16W6 - Well E - plug erosion")

    def test_a_stage_chart_is_not_unnumbered(self):
        self.assertIsNone(bj1.unnumbered_title(_Page(CHART)))

    def test_no_time_axis_is_not_a_chart(self):
        self.assertIsNone(bj1.unnumbered_title(
            _Page("102-09-28-79-16W6 - Well E - plug erosion\n")))


if __name__ == "__main__":
    unittest.main()
