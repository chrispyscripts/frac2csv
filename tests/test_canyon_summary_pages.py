"""A page that merely says "Treatment Summary" is not a Treatment Summary.

`canyon_tables.find_summary_pages` is what fills the Lab's Tables tab with
rendered source pages, and `_page_kind` matched those two words anywhere on a
page. Two client reports, both on Halliburton filings that contain no Canyon
page at all, and in both the tab opened on nothing but pictures of pages that
carry no table:

  * 00453 (#705, "extracting stage summary screenshots in tables, not no
    table") — 44 pages: 2, 5, 8, 10, 13, 15, 20 ... 147. Every Peloton "Daily
    Completion and WS (board report)" sheet prints "Stimulation & Treatment
    Summary" as one of a dozen section bars down a daily ops page, and on
    this filing the box under it is empty. 35 groups, 44 rendered pages.

  * 00971 (#710, "no table data, 1 source page is a table of contents") —
    p111, the Halliburton IFS Table of Contents, whose line reads
    "Treatment Summary ............................... 4". One group, one
    page, and it is literally a table of contents.

Neither is one file. A random 24-file sweep of the corpus listed 102 pages
before this change and 43 after. The 59 that go are three more Peloton
filings' section bars — 00583 (22), 00946 (21), 00592 (15), and on each of
those, as on 00453, that bar is the only way the words appear in the file —
plus 00973 p99, a contents page in the same Halliburton book as 00971's.

The 43 that stay matter as much, because for some of them the listing is the
ONLY thing that reaches the client — they do not parse:

  * 00553 p165 — Schlumberger "Stage-by-Stage Treatment Summary", 36 stage
    rows. canyon_tables cannot read it (it prints "Port Open", not "Port
    Opening", so is_treatment_summary_page says no).
  * 00531 p142 — CalFrac "Treatment Summary - Well Total / All Zones", the
    whole-well fluid, proppant and chemical roll-up. calfrac_summary lists
    p143-148 and parses 29 rows from them; p142 is not among them.

The rest of the 43 are 01091 (19 pages) and 01464 (15), both CalFrac, and
00065 (1) — every one unchanged.

Run: python3 -m pytest tests/test_canyon_summary_pages.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canyon_tables                                     # noqa: E402


class _Page(object):
    def __init__(self, text):
        self._text = text

    def get_text(self, *a, **k):
        return self._text


class _Doc(object):
    """Enough of a fitz.Document for find_summary_pages."""

    def __init__(self, pages):
        self._pages = pages
        self.page_count = len(pages)

    def __getitem__(self, i):
        return self._pages[i]


def _listed(texts):
    """The 1-based pages find_summary_pages would put in the Tables tab."""
    doc = _Doc([_Page(t) for t in texts])
    return sorted({p for g in canyon_tables.find_summary_pages(doc)
                   for p in g["pages"]})


# 00453 p2, as its text layer extracts: section bars down a daily ops page.
PELOTON_DAILY = """Page 1/2
Well Name: ARC RESOURCES 102 KAKWA 1-26-63-6
Daily Completion and WS (board report)
Stimulation & Treatment Summary
Start Date
Zone
Type
Deliv Mode
Company
2/28/2023
Upper Montney, Original Hole
Hydraulic Frac
Casing
HALLIBURTON GROUP CANADA INC.
Stimulation Stages
Interval Number
Top (mKB)
Btm (mKB)
Vol Clean Total OR (m3)
Tubing Run
Cement
www.peloton.com
"""

# 00971 p111, as its text layer extracts: one contents entry per line.
IFS_CONTENTS = """0002
CREW ENERGY INC
UWI: 100/04-13-081-22W6
(IFS v 7)
Table of Contents
Executive Summary""" + "." * 60 + """
Treatment Summary """ + "." * 60 + """ 4
Well Information""" + "." * 60 + """ 5
1.1
Stage Summary """ + "." * 60 + """ 7
"""

# 00553 p165's banner, and 00531 p142's.
SLB_SHEET = ("Customer: Black Swan Energy Ltd\n"
             "Stage-by-Stage Treatment Summary\nZone\nFluid\nPort Open\n")
CALFRAC_TOTAL = ("Treatment Summary - Well Total\nAll Zones\n"
                 "UWI: 200/d-006-K/094-B-16/00\n"
                 "Calfrac Service Line: Fracturing\n")


class WhatIsNotASummarySheet(unittest.TestCase):
    """Asserted through find_summary_pages, because that list IS what the
    Tables tab renders — these are the pages the client was shown."""

    def test_a_daily_reports_section_bar_is_not_one(self):
        """#705: 44 of these were listed on 00453, none of them a table."""
        self.assertEqual(_listed([PELOTON_DAILY, PELOTON_DAILY]), [])

    def test_a_table_of_contents_is_not_one(self):
        """#710: 00971 p111 was the single source page in the Tables tab."""
        self.assertEqual(_listed([IFS_CONTENTS]), [])

    def test_the_pages_really_do_print_the_words(self):
        """Stated so the two guards cannot pass for the wrong reason."""
        self.assertIn("Treatment Summary", PELOTON_DAILY)
        self.assertIn("Treatment Summary", IFS_CONTENTS)


class WhatIs(unittest.TestCase):
    """Only these two lines are excluded, and nothing else is."""

    def test_an_odd_heading_is_still_a_heading(self):
        """00553 p165 and 00531 p142. Neither parses, so being listed for
        viewing is the whole of what the client gets."""
        self.assertEqual(_listed([SLB_SHEET]), [1])
        self.assertEqual(_listed([CALFRAC_TOTAL]), [1])

    def test_a_bare_heading_is_still_a_heading(self):
        self.assertEqual(_listed(["Treatment Summary\nUWI:\nWell License:"]),
                         [1])

    def test_one_real_sheet_among_the_daily_pages_still_lists(self):
        self.assertEqual(
            _listed([PELOTON_DAILY, SLB_SHEET, IFS_CONTENTS]), [2])

    def test_and_is_excluded_as_well_as_ampersand(self):
        """The same bar, spelled out. Written as one pattern, so say so."""
        self.assertEqual(
            _listed(["Stimulation and Treatment Summary\nStart Date\n"]), [])


if __name__ == "__main__":
    unittest.main()
