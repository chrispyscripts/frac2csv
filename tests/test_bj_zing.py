"""BJ's 2026 ZingChart render (#796, #797): read, named, and on the clock.

00057's charts came back empty — no BJ-1 title, no "Mon-DD HH:MM" clock, so
bj1 never recognised a page. bj_zing reads them off the text and the vector
strokes. Checked against the page: stage 29 on p315 runs 21:34:44-23:00:04
on 24 Mar 26, its pressure peaks near 74 MPa and its rate near 9.3.

  python3 -m unittest tests.test_bj_zing
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import aliases                                           # noqa: E402
import bj_zing                                           # noqa: E402

SPUD = os.path.expanduser("~/frac-data/BCER-Frac-Spud-2026")


def _pdf(num):
    hits = glob.glob(os.path.join(SPUD, f"{num}-*.pdf"))
    return hits[0] if hits else None


class Names(unittest.TestCase):

    def test_the_zingchart_names_map_to_our_terms(self):
        self.assertEqual(aliases.canon("SIDE 1 WH-Press"), "Tr Press")
        self.assertEqual(aliases.canon("SIDE 2-WH-Press"), "Tr Press")
        self.assertEqual(aliases.canon("CMB-SLR-Rate"), "Slurry Rate")
        self.assertEqual(aliases.canon("Bld1-WH-Density"), "WH Prop Conc")
        self.assertEqual(aliases.canon("Bld2-WH-Density"), "WH Prop Conc")
        self.assertEqual(aliases.canon("Density at Perfs"), "BH Prop Conc")


@unittest.skipUnless(_pdf("00057"), "the 2026 BJ filings are not on this machine")
class Sunrise(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import fitz
        cls.doc = fitz.open(_pdf("00057"))

    def test_p315_stage_29(self):
        page = self.doc[314]
        self.assertTrue(bj_zing.detect(page))
        meta, samples, data, units = bj_zing.extract_page(page)
        self.assertEqual(meta.stage, "29")
        self.assertEqual(meta.uwi, "103/07-34-078-17W6/00")
        self.assertEqual(meta.date, "2026-03-24")
        self.assertTrue(meta.start_time.startswith("21:34"))
        self.assertAlmostEqual(meta.duration_min, 85.3, delta=0.5)
        self.assertEqual(set(data), {"SIDE 1 WH-Press", "CMB-SLR-Rate",
                                     "Bld1-WH-Density", "Density at Perfs"})
        self.assertAlmostEqual(float(np.nanmax(data["SIDE 1 WH-Press"])), 74, delta=1.5)
        self.assertAlmostEqual(float(np.nanmax(data["CMB-SLR-Rate"])), 9.3, delta=0.3)
        self.assertEqual(units["CMB-SLR-Rate"], "m3/min")
        self.assertEqual(meta.axes["Density at Perfs"], (0.0, 2000.0))

    def test_every_chart_page_reads(self):
        pages = [p for p in self.doc if bj_zing.detect(p)]
        self.assertEqual(len(pages), 94)
        for p in pages:
            bj_zing.extract_page(p)


@unittest.skipUnless(_pdf("00060"), "the 2026 BJ filings are not on this machine")
class OneBadDate(unittest.TestCase):

    def test_00060_p221_a_misdated_label_is_outvoted(self):
        import fitz
        meta, samples, data, units = bj_zing.extract_page(fitz.open(_pdf("00060"))[220])
        self.assertEqual(meta.date, "2026-03-27")
        self.assertAlmostEqual(meta.duration_min, 107.5, delta=1.0)


if __name__ == "__main__":
    unittest.main()


class EmptyChart(unittest.TestCase):
    """00019 p124 (#801): stage 41's chart printed with no data at all."""

    class Page:
        def __init__(self, text):
            self.text = text

        def get_text(self):
            return self.text

    def test_a_titled_page_with_no_time_axis_is_empty(self):
        import bj_zing
        p = self.Page("OVV HZ SUNRISE H3-19-78-16 | 41 | Stage 41 | API/UWI: 102/07-34-078-17-W6/00 "
                      "| Ovintiv 03-19 Pad\nLocal Time\n0\n100\nPowered by ZingChart")
        self.assertEqual(bj_zing.empty_chart(p), "41")

    def test_a_page_with_its_clock_is_not(self):
        import bj_zing
        p = self.Page("OVV HZ SUNRISE H3-19-78-16 | 40 | Stage 40 | API/UWI: 102/07-34-078-17-W6/00 "
                      "| Ovintiv 03-19 Pad\n28 Mar 26\n19:26:41\nPowered by ZingChart")
        self.assertIsNone(bj_zing.empty_chart(p))
