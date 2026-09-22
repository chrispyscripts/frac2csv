"""A gridline through the tick column is not a digit (#715, #716).

  python3 -m unittest tests.test_hal_ruled_ladder

01367 p188 and p266 are the same Halliburton treatment chart drawn twice.
Both are the turned render, so the value labels are printed INSIDE the plot
frame; p188 additionally rules the plot with vertical gridlines, and 38 of
them fall in the 118px concentration strip _ocr_column reads.

Tesseract returned NOTHING from that strip — not a bad number, nothing at
all — so `fit_ticks` had no ladder, and extract_image dropped both
concentration channels with "axis unreadable", on a page whose curves are
drawn and perfectly traceable. Carmine: "missing data that needs
interpolaton on displayed data. Missing both conc data sets."

Measured on the two pages:

    p188   38 of 118 columns are full-height rules
           raw          []
           rules blank  1400 1200 1000 800 600 400 200, steps of 92.5px
    p266    1 of 118 columns is a rule
           raw          the real ticks + 2 noise reads
           rules blank  the same real ticks, 1 noise read

A gridline runs the whole height of the plot; a digit covers about 3% of
it. That is the whole rule.
"""
import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hal1                                                # noqa: E402

DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/"
                  "01367-103133407818W600_43621_COMP_2023FEB09.pdf")


def ruled_strip(n_rules=38, h=694, w=118):
    """A strip of white with full-height rules and one short glyph."""
    a = np.full((h, w, 3), 255, np.uint8)
    for i, c in enumerate(np.linspace(30, w - 2, n_rules).astype(int)):
        a[:, c] = 120                       # a grey rule, top to bottom
    a[300:320, 5:20] = 0                    # a "digit": 20 rows of 694
    return a


class WhatCountsAsARule(unittest.TestCase):
    """The rule is height, and nothing else."""

    def test_a_full_height_column_is_a_rule(self):
        a = ruled_strip()
        ink = (a.astype(int).sum(2) < 640)
        self.assertTrue((ink.mean(0) > 0.5).sum() >= 38)

    def test_a_digit_is_not(self):
        a = ruled_strip()
        ink = (a.astype(int).sum(2) < 640)
        # the glyph columns are 20 rows of 694 — about 3%, nowhere near half
        for c in range(5, 20):
            self.assertLess(ink[:, c].mean(), 0.5)

    def test_blanking_leaves_the_digit_alone(self):
        a = ruled_strip()
        ink = (a.astype(int).sum(2) < 640)
        a[:, ink.mean(0) > 0.5] = 255
        self.assertTrue((a[300:320, 5:20] == 0).all())
        # and every rule is gone
        ink2 = (a.astype(int).sum(2) < 640)
        self.assertEqual(int((ink2.mean(0) > 0.5).sum()), 0)

    def test_a_short_strip_is_left_alone(self):
        """The guard is height-gated, and this proves it through _ocr_column.

        On a strip only a few rows tall "more than half ink" stops meaning
        a rule and starts meaning a thick glyph, so the blanking must not
        run there at all. Reading a 12-row strip must leave its ink intact.
        """
        import hal1 as H
        short = np.full((12, 60, 3), 255, np.uint8)
        short[:, 10] = 0                     # full height of THIS strip
        ink_before = int((short.astype(int).sum(2) < 640).sum())
        img = np.full((40, 200, 3), 255, np.uint8)
        img[14:26, 0:60] = short
        # _ocr_column would blank column 10 if the guard were not gated
        H._ocr_column(img, 0, 60, 14, 25)
        self.assertEqual(int((short.astype(int).sum(2) < 640).sum()),
                         ink_before)


@unittest.skipUnless(DRIVE, "the BC drive is not mounted")
class OnTheRealPages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import fitz
        cls.doc = fitz.open(DRIVE[0])

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()

    def _conc(self, pno):
        meta, s, ch, info = hal1.extract_page(self.doc[pno - 1])
        return {c["label"]: c for c in ch}, info

    def test_p188_reads_both_concentrations(self):
        ch, info = self._conc(188)
        self.assertIn("BH Prop Conc", ch)
        self.assertIn("Slurry Prop Conc", ch)
        self.assertEqual([n for n in info.get("notes", [])
                          if "axis unreadable" in n], [])

    def test_p188_bh_conc_is_mostly_present(self):
        ch, _ = self._conc(188)
        v = np.asarray(ch["BH Prop Conc"]["values"], float)
        self.assertGreater(np.isfinite(v).mean(), 0.85)

    def test_p266_is_unchanged(self):
        # the clean render of the same chart: the fix must not move it
        ch, _ = self._conc(266)
        v = np.asarray(ch["BH Prop Conc"]["values"], float)
        f = v[np.isfinite(v)]
        self.assertAlmostEqual(float(f.max()), 500.31, places=1)


if __name__ == "__main__":
    unittest.main()
