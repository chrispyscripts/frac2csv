"""A log finds its printout in the printouts folder by name.

The folder is laid out like the WellSight drive: the prints as LogViewer made
them in HLG\\Pdf and SLG\\PDF-with-PNG, and the hand-made copies deeper down
(pages turned, ".pdf.pdf"; stacked by hand, "_stitched"; turned again,
"_stitched_rot270"; SVGs). The print as LogViewer made it wins.

Run: python3 -m unittest tests.test_wellsight_library
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wellsight_library as lib                                # noqa: E402


def touch(root, rel):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").close()
    return p


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.root = self.tmp.name
        self.raw = touch(r, "s-h-sl/HLG/Pdf/0005--07I231_LP-LAT_LEG_1.pdf")
        touch(r, "s-h-sl/HLG/Pdf/Rotated/0005--07I231_LP-LAT_LEG_1.pdf.pdf")
        touch(r, "s-h-sl/HLG/Pdf/Rotated/DL-Stitcher/0005--07i231_lp-lat_leg_1.pdf_stitched.pdf")
        touch(r, "s-h-sl/HLG/Pdf/Rotated/DL-Stitcher/R-L/PDF/0005--07i231_lp-lat_leg_1.pdf_stitched_rot270.pdf")
        touch(r, "s-h-sl/HLG/Pdf/Rotated/DL-Stitcher/R-L/SVG/0005--07i231_lp-lat_leg_1.pdf_stitched_rot270.svg")
        self.slg = touch(r, "s-h-sl/SLG/PDF-with-PNG/0229--10C057_LOG_HZ_Build.pdf")
        touch(r, "s-h-sl/SLG/PDF-with-PNG/DL-Stitch/0229--10c057_log_hz_build_stitched.pdf")
        touch(r, "s-h-sl/SLG/PDF-with-PNG/._0229--10C057_LOG_HZ_Build.pdf")   # macOS litter
        self.only_stacked = touch(r, "s-h-sl/SLG/PDF-with-PNG/DL-Stitch/0300--x_build_stitched.pdf")
        self.ix = lib.index(self.root, refresh=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_names_shared_by_a_log_and_its_printouts(self):
        for n in ("0005--07I231_LP-LAT_LEG_1.hl6", "0005--07I231_LP-LAT_LEG_1.pdf",
                  "0005--07I231_LP-LAT_LEG_1.pdf.pdf", "0005--07i231_lp-lat_leg_1.pdf_stitched.pdf",
                  "0005--07i231_lp-lat_leg_1.pdf_stitched_rot270.pdf"):
            self.assertEqual(lib.stem(n), "0005--07i231_lp-lat_leg_1", n)

    def test_the_print_as_logviewer_made_it_wins(self):
        path, kind = lib.find(self.ix, "0005--07I231_LP-LAT_LEG_1.hl6")
        self.assertEqual(path, self.raw)
        self.assertEqual(kind, "print")
        path, kind = lib.find(self.ix, "0229--10C057_LOG_HZ_Build.slg")
        self.assertEqual(path, self.slg)

    def test_a_hand_stacked_copy_only_when_nothing_else(self):
        path, kind = lib.find(self.ix, "0300--x_build.sl6")
        self.assertEqual(path, self.only_stacked)
        self.assertEqual(kind, "stacked")

    def test_a_renamed_log_found_by_its_number(self):
        path, kind = lib.find(self.ix, "0005--renamed.hl6")
        self.assertEqual(path, self.raw)

    def test_not_there(self):
        path, why = lib.find(self.ix, "9999--nothing.sl6")
        self.assertIsNone(path)
        self.assertIn("9999--nothing.pdf", why)

    def test_counts_and_litter(self):
        self.assertEqual(self.ix["pdfs"], 7)           # SVGs and ._ files left out
        self.assertEqual(self.ix["prints"], 2)

    def test_missing_folder_says_so(self):
        with self.assertRaises(FileNotFoundError):
            lib.index(os.path.join(self.root, "nope"), refresh=True)


if __name__ == "__main__":
    unittest.main()
