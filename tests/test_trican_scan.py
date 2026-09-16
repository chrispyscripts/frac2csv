"""Layout A photocopied (00006-00008): frames found on the page image.

  python3 -m unittest tests.test_trican_scan
"""
import glob
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc                                 # noqa: E402


def page_with_frames(frames, H=1631, W=1268, left_faint=True):
    img = np.full((H, W, 3), 245, int)
    for x0, y0, x1, y1 in frames:
        img[y0:y0 + 2, x0:x1] = 40                 # top edge
        img[y1:y1 + 2, x0:x1] = 40                 # bottom edge
        img[y0:y1, x1:x1 + 2] = 40                 # right edge
        # the scan's left edge: broken, so a column test at 60% fails
        for y in range(y0, y1, 3):
            img[y, x0:x0 + 2] = 40 if not left_faint or y % 9 else 200
    return img


class ScanFrames(unittest.TestCase):
    FRAMES = [(213, 457, 1095, 770), (213, 1102, 1095, 1376)]

    def test_both_frames_top_first(self):
        got = tc.scan_frames(page_with_frames(self.FRAMES))
        self.assertEqual(len(got), 2)
        for (x0, y0, x1, y1), (ex0, ey0, ex1, ey1) in zip(got, self.FRAMES):
            self.assertLessEqual(abs(x0 - ex0), 2); self.assertLessEqual(abs(y0 - ey0), 2)
            self.assertLessEqual(abs(x1 - ex1), 3); self.assertLessEqual(abs(y1 - ey1), 3)

    def test_a_short_rule_is_not_an_edge(self):
        img = page_with_frames(self.FRAMES)
        img[110:112, 300:700] = 40                 # a header underline
        self.assertEqual(len(tc.scan_frames(img)), 2)

    def test_the_column_test_alone_finds_nothing(self):
        from step1 import _frame_bbox
        self.assertIsNone(_frame_bbox(page_with_frames(self.FRAMES)))

    def test_no_frames_on_a_blank_page(self):
        self.assertEqual(tc.scan_frames(np.full((400, 600, 3), 245, int)), [])


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/AER-Frac-*/00006-100130505522W500*")


@unittest.skipUnless(DRIVE, "the AER drive is not mounted")
class OnTheScan(unittest.TestCase):

    def test_00006_p42_reads_six_channels(self):
        import fitz
        pg = fitz.open(DRIVE[0])[41]
        meta, samples, channels, info = tc.extract_page(pg)
        self.assertEqual(meta["stage"], 1)
        self.assertGreaterEqual(len(channels), 5)
        self.assertAlmostEqual(len(samples) / 60.0, 53.4, delta=2)
        self.assertTrue(any("scanned page" in n for n in info["notes"]))


if __name__ == "__main__":
    unittest.main()
