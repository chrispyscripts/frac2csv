"""Liberty's re-frac letter in either case: "Stage 3a" (01732 p207, #649).

  python3 -m unittest tests.test_lib1_refrac_letter
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib1                                                # noqa: E402

# the module's own pattern, not a copy of it — a copy drifts
PAT = re.compile(lib1._STAGE_TOKEN)


class ReFracLetter(unittest.TestCase):

    def test_the_pattern_takes_either_case(self):
        self.assertEqual(PAT.search("Middle Montney Stage 3a").group(1), "3a")
        self.assertEqual(PAT.search("Stage 4A HRF").group(1), "4A HRF")
        self.assertEqual(PAT.search("Stage 01 of 47").group(1), "01")

    def test_a_tag_printed_against_the_number_is_still_the_stage(self):
        # 01004 p171 and p207: "LMA - Stage 10HRF", no space before the tag.
        # Requiring one refused the whole token and both pages filed as no
        # stage at all, reaching the client as "Stage ?" (#714).
        self.assertEqual(PAT.search("LMA - Stage 10HRF").group(1), "10HRF")
        self.assertEqual(PAT.search("LMA - Stage 25HRF").group(1), "25HRF")

    def test_every_other_shape_this_module_reads_is_unchanged(self):
        # the space becoming optional must not widen anything else, so the
        # shapes lib1 has had to read are pinned here one by one
        for text, want in (("LMA - Stage 9", "9"),
                           ("Stage 6A PW", "6A PW"),
                           ("Stage 14A - HRF", "14A - HRF"),
                           ("Stage HRF 5A", "HRF 5A"),
                           ("Stage 2B", "2B"),
                           ("Stage 12 MPa", "12"),
                           ("Stage 7 and the rest", "7"),
                           ("Stage 3 Part II", "3")):
            with self.subTest(text=text):
                self.assertEqual(PAT.search(text).group(1), want)


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/01732-203A059I094B0900*")


@unittest.skipUnless(DRIVE, "the BC drive is not mounted")
class OnThePage(unittest.TestCase):

    def test_01732_p207_is_stage_3a(self):
        import fitz
        doc = fitz.open(DRIVE[0])
        self.assertEqual(lib1.extract_page(doc[206])[0].stage, "3a")
        self.assertEqual(lib1.extract_page(doc[204])[0].stage, "3")


if __name__ == "__main__":
    unittest.main()
