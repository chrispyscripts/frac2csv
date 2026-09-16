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

PAT = re.compile(rf"{lib1._STAGE}\s+((?:[A-Z]{{2,4}}\s+)?\d+[A-Za-z]?"
                 r"(?:\s*-\s*[A-Z]{2,4})?(?:[ \t]+[A-Z]{2,4})?)\b()")


class ReFracLetter(unittest.TestCase):

    def test_the_pattern_takes_either_case(self):
        self.assertEqual(PAT.search("Middle Montney Stage 3a").group(1), "3a")
        self.assertEqual(PAT.search("Stage 4A HRF").group(1), "4A HRF")
        self.assertEqual(PAT.search("Stage 01 of 47").group(1), "01")


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
