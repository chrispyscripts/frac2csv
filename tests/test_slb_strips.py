"""A Zone Summary chart filed as a stack of image strips (00118, Husky 2019).

  python3 -m unittest tests.test_slb_strips
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import slb                                                 # noqa: E402

DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/AER-Frac-*/00118-102120205119W500*")


@unittest.skipUnless(DRIVE, "the AER drive is not mounted")
class StripStack(unittest.TestCase):

    def test_p84_is_a_raster_zone_sheet_read_from_its_strips(self):
        import fitz
        pg = fitz.open(DRIVE[0])[83]
        self.assertIsNone(slb._chart_image(pg))
        rect, scale = slb._strip_stack(pg)
        self.assertGreater(rect.height, 250)
        self.assertAlmostEqual(scale, 3.06, delta=0.05)
        self.assertEqual(slb.page_chart_kind(pg), "raster")
        meta, samples, data, units = slb.extract_zone_page(pg)
        self.assertEqual(str(meta.stage), "6")
        self.assertIn("Tr Press", data)
        self.assertIn("Slurry Rate", data)


if __name__ == "__main__":
    unittest.main()
