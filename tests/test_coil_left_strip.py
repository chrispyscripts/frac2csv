"""A coil-tubing stage's left strip: TP Rate 0..1000 outside Pressure 0..80.

auto_raster now takes a ladder whose labels lie on one line to the pixel, so
the two ladders together fit the TP Rate one by themselves, and step1 picked
between the pressure crops by tick count: 00243 p77 took the one with the
first time label's "2" under the frame, and Surface Pressure went out on
5..80. Where no crop agrees with the whole strip, the pressure column is read
on its own, as where the strip fits nothing.

  python3 -m unittest tests.test_coil_left_strip
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DRIVE = glob.glob("/Volumes/For-Chris-CnC-1TB/BCER-Frac/00243-*/00243-*.PDF")


@unittest.skipUnless(DRIVE, "the BCER drive is not mounted")
class CoilStage(unittest.TestCase):

    def test_00243_p77_pressure_on_0_to_80(self):
        import fitz
        import step1
        _md, charts = step1.extract_page(fitz.open(DRIVE[0])[76])
        chans = {c["label"]: [v for v in c["values"] if v == v]
                 for tag, _s, ch, _i in charts if tag == "t" for c in ch}
        sp = chans["Surface Pressure"]
        # the page: 22 MPa at the 21:04 dip, 56.7 at the top
        self.assertAlmostEqual(min(sp), 22.0, delta=1.0)
        self.assertAlmostEqual(max(sp), 56.7, delta=1.0)


if __name__ == "__main__":
    unittest.main()
