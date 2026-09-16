"""Scanned CalFrac/MView overview pages (00019, 00031, 00035 — 2018 scans).

  python3 -m unittest tests.test_calfrac_scan
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calfrac_scan as cs                                  # noqa: E402

SURF = ("Tourmaline 100/09-07-062-05W6/00 Surface Treating Pressure (MPa) "
        "Blender Slurry Rate (m3/min) Zones 1-19 Master Conc @ Blender (kg/m3) "
        "100 80 60 40 20 0 0 100 200 300 400 500 600 700 Time (min) "
        "MView - CWS-600 Ball Job Casing Bob C - 3/4/2018")
BH = ("Tourmaline 100/09-07-062-05W6/00 Bottom Hole Treating Pressure (MPa) "
      "Combined Rate @ Formation (m3/min) Bottom Hole Pressure (MPa)")
TAQA = ("1 AVA IN orth 1 UU/ 14-i.2-U4i-U9 W NUU urtace Treating Pressure (MPa) "
        "Blender Slurry Rate (m3/min) Annulus Pressure (MPa) Zones 1-16 "
        "N2 Rate (sm3/min) Master Conc @ Blender (kg/m' 10 100 500 1000")
CHEM = ("Tourmaline 100/09-07-062-05W6/00 Chemicals Blender Clean Rate (m3/min) "
        "DWP-621 Friction Reducer Conc (L/m3) Time (min)")


class Variant(unittest.TestCase):

    def test_the_title_names_the_page(self):
        self.assertEqual(cs.variant(SURF), " Surface")
        self.assertEqual(cs.variant(BH), " BH")

    def test_a_garbled_title_is_read_from_the_legend(self):
        # "urtace" — but only the Surface page plots the Blender Slurry Rate
        self.assertEqual(cs.variant(TAQA), " Surface")
        self.assertEqual(cs.variant("AQA North Bottom Hole Treating Pressure "
                                    "Combined Rate @ Formation (remin)"), " BH")

    def test_the_chemicals_page_is_neither(self):
        self.assertEqual(cs.variant(CHEM), "")


class RightLadders(unittest.TestCase):
    # p43 of 00019 as the right strip reads: rate 0..15 and conc 0..500
    # interleaved, 390 px apart, the zero shared
    # frame rows 371..2324: the labels sit on their gridlines, 390.6 px apart
    PTS = [(500, 371), (12, 762), (400, 762), (9, 1152), (300, 1152),
           (6, 1543), (200, 1543), (3, 1933), (100, 1933), (0, 2324)]

    def test_rate_and_conc_are_told_apart_by_magnitude(self):
        rate, conc, other = cs.split_right(self.PTS)
        self.assertEqual(sorted(v for v, _ in rate), [0, 3, 6, 9, 12])
        self.assertEqual(sorted(v for v, _ in conc), [0, 100, 200, 300, 400, 500])
        self.assertEqual(other, [])

    def test_an_n2_ladder_is_the_lower_of_two(self):
        # TAQA: N2 0..500 beside conc 0..1000, both in the hundreds
        pts = [(1000, 371), (500, 371), (800, 762), (400, 762), (600, 1152),
               (300, 1152), (400, 1543), (200, 1543), (200, 1933), (100, 1933),
               (0, 2324), (10, 371), (8, 762), (6, 1152), (4, 1543), (2, 1933)]
        rate, conc, other = cs.split_right(pts)
        self.assertEqual(max(v for v, _ in conc), 1000)
        self.assertEqual(sorted(v for v, _ in other), [100, 200, 300, 400, 500])
        self.assertEqual(sorted(v for v, _ in rate), [0, 2, 4, 6, 8, 10])

    def test_axis_snaps_to_the_frame(self):
        rate, conc, _ = cs.split_right(self.PTS)
        a, b = cs.axis(conc, 371, 2324)
        self.assertAlmostEqual(a + b * 371, 500.0, places=3)
        self.assertAlmostEqual(a + b * 2324, 0.0, places=3)

    def test_too_few_labels_is_no_axis(self):
        self.assertIsNone(cs.axis([(0, 2340), (100, 2003)], 371, 2324))

    def test_a_pressure_ladder_ignores_misread_digits(self):
        # 00035 p116's left strip: 60 and 40 read as "3", "260", "2", "4", "4"
        # — four junk readings as straight as the four true ones, and the
        # fit through them gave a 1..5 MPa axis
        pts = [(100, 317), (80, 594), (3, 835), (260, 869), (2, 928),
               (4, 1156), (4, 1218), (20, 1424), (0, 1700)]
        a, b = cs.axis(pts, 327, 1712, kind="pressure")
        self.assertAlmostEqual(a + b * 327, 100.0, delta=2)
        self.assertAlmostEqual(a + b * 1712, 0.0, delta=2)

    def test_an_implausible_pressure_axis_is_refused(self):
        self.assertIsNone(cs.axis([(3, 835), (2, 928), (4, 1156), (4, 1218)],
                                  327, 1712, kind="pressure"))


class Captions(unittest.TestCase):

    def test_zones_uwi_and_date(self):
        z = cs._ZONES.search(SURF); d = cs._DATE.search(SURF); u = cs._UWI.search(SURF)
        self.assertEqual((z.group(1), z.group(2)), ("1", "19"))
        self.assertEqual(d.groups(), ("3", "4", "2018"))
        self.assertEqual(u.group(0), "100/09-07-062-05W6/00")


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/AER-Frac-*/00019-100090706205W600_0484873_COMP.PDF")


@unittest.skipUnless(DRIVE, "the AER drive is not mounted")
class OnTheScan(unittest.TestCase):

    def test_00019_p43_reads_the_surface_overview(self):
        import fitz
        doc = fitz.open(DRIVE[0])
        self.assertTrue(cs.detect(doc[42]))
        self.assertFalse(cs.detect(doc[44]))            # Chemicals
        meta, samples, data, units, info = cs.extract_page(doc[42])
        self.assertEqual(meta["stage"], "Zones 1-19 Surface")
        self.assertEqual(meta["date"], "2018-03-04")
        self.assertIn("Treating Pressure", data)
        self.assertIn("Blender Slurry Rate", data)
        self.assertAlmostEqual(len(samples) / 60.0, 700, delta=15)


if __name__ == "__main__":
    unittest.main()
