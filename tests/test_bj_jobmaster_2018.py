"""JobMaster 2018 (00575): the title without "Well N", the page text read
off the ink when the font names no characters.

  python3 -m unittest tests.test_bj_jobmaster_2018
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bj1                                                 # noqa: E402

P101 = ("BJ Services\nJob Start: Wednesday, May 09, 2018\n0\n50\n100\nWH Press (MPa)\n"
        "Calculated BHP (MPa)\n0\n5\n10\n15\n20\nSLR Rate (m3/min)\n830\n840\n850\n"
        "Elapsed Time (min)\nRIFE 100/01-24 Zone 6\nJobMaste!\nT Program Version 4.02C1\n"
        "UWI: 100/01-24-032-24W4")
P56 = "102/05-26-062-21W5 Well 2 Zone 1\nJobMaster Program Version 4.02C1\nElapsed Time (min)"


class Title(unittest.TestCase):

    def test_2019_well_and_zone(self):
        self.assertEqual(bj1.jm_title(P56), ("Well 2", 1))

    def test_2018_operator_location_and_zone(self):
        self.assertEqual(bj1.jm_title(P101), ("RIFE 100/01-24", 6))

    def test_additives_page_keeps_its_word(self):
        self.assertEqual(bj1.jm_title("Additives 100/01-24 Zone 9"), ("Additives 100/01-24", 9))

    def test_the_dash_and_the_glued_well_number(self):
        self.assertEqual(bj1.jm_title("Vesta 100/10-20  Well 1 - Zone 1"), ("Vesta 100/10-20 Well 1", 1))
        self.assertEqual(bj1.jm_title("102/04-26-062-21W5 Well1 Zone 1"), ("102/04-26-062-21W5 Well 1", 1))
        self.assertEqual(bj1.jm_title("Vesta Additives 100/10-20 Zone 1"), ("Vesta Additives 100/10-20", 1))

    def test_interval_is_zone(self):
        self.assertEqual(bj1.jm_title("Well A interval 1"), ("Well A", 1))
        self.assertEqual(bj1.jm_title("Well B Interval 17"), ("Well B", 17))
        self.assertIsNone(bj1.jm_title("Additives 1 - 4"))

    def test_frac_number_and_its_qualifier(self):
        self.assertEqual(bj1.jm_title("Husky 100/06-24-048-19W5 Frac #2"), ("Husky 100/06-24-048-19W5", 2))
        self.assertEqual(bj1.jm_title("Husky 100/06-24-048-19W5 Frac #2 Ball Seat Attempt", word=True),
                         ("Husky 100/06-24-048-19W5", 2, "Frac #", "Ball Seat Attempt"))
        self.assertEqual(bj1.jm_title("Well A interval 1", word=True), ("Well A", 1, "Interval", ""))
        self.assertIsNone(bj1.jm_title("Additives"))

    def test_the_shifted_font_reads_back(self):
        # 00030: every code 29 below its character
        self.assertEqual(bj1._unshift("-RE0DVWHU\x033URJUDP"), "JobMaster Program")
        self.assertEqual(bj1._unshift("=RQH\x03\x14"), "Zone 1")
        self.assertEqual(bj1._unshift("Job Number:  PRJ1001029"), "Job Number:  PRJ1001029")
        self.assertEqual(bj1._unshift(""), "")

    def test_2019_additives_page_names_no_zone(self):
        self.assertIsNone(bj1.jm_title("Slickwater Additives"))

    def test_is_jobmaster_survives_the_ocr_of_the_banner(self):
        # the banner's "JobMaster" reads "JobMaste!" off the ink
        self.assertTrue(bj1.is_jobmaster(P101))
        self.assertTrue(bj1.is_jobmaster(P56))
        self.assertFalse(bj1.is_jobmaster("Elapsed Time (min)\nZone 6"))

    def test_uwi_from_the_2018_header(self):
        m = bj1._JM_UWI.search(P101)
        self.assertEqual("{}{}{}{}{}W{}00".format(*m.groups()), "100012403224W400")


class CubicUnits(unittest.TestCase):
    # the substitution span_text applies to what tesseract makes of m³
    SUB = (r"(?<=m)[*?³](?=/|\)|$)", "3")

    def test_superscripts_read_as_three(self):
        for raw, want in (("SLR Rate (m*/min)", "SLR Rate (m3/min)"),
                          ("CLN Rate* (m?/min)", "CLN Rate* (m3/min)"),
                          ("WH Density (kg/m³)", "WH Density (kg/m3)"),
                          ("Density at Perfs (kg/m*)", "Density at Perfs (kg/m3)")):
            self.assertEqual(re.sub(*self.SUB, raw), want)

    def test_a_bare_star_is_left_alone(self):
        self.assertEqual(re.sub(*self.SUB, "CLN Rate*"), "CLN Rate*")


if __name__ == "__main__":
    unittest.main()
