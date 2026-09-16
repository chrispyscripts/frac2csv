"""BJ JobMaster charts (2019 Duvernay): rotated pages, elapsed minutes, no legend.

  python3 -m unittest tests.test_bj_jobmaster
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bj1                                               # noqa: E402


class _Page(object):
    def __init__(self, text):
        self._text = text

    def get_text(self, *a, **k):
        return self._text


JM = ("JobMaster Program Version 4.02C1\nJob Number:  PRJ1001692\nCustomer:    Chevron Canada Limited\n"
      "Well Name:   102/05-26-062-21W5\nBJ Services\nJob Start:  Friday, May 31, 2019\n"
      "WH Press (MPa)\nElapsed Time (min)\n102/05-26-062-21W5 Well 2 Zone 1\n")


class Detect(unittest.TestCase):

    def test_a_jobmaster_zone_page_is_a_bj_chart(self):
        self.assertTrue(bj1.is_jobmaster(JM))
        self.assertTrue(bj1.detect(_Page(JM)))

    def test_the_additives_page_is_not(self):
        t = JM.replace("102/05-26-062-21W5 Well 2 Zone 1\n", "Slickwater Additives\n")
        self.assertFalse(bj1.is_jobmaster(t))
        self.assertFalse(bj1.detect(_Page(t)))

    def test_the_well_and_the_zone_read(self):
        w = bj1._JM_WELL.search(JM); z = bj1._JM_ZONE.search(JM); s = bj1._JM_START.search(JM)
        self.assertEqual("{}{}{}{}{}W{}00".format(*w.groups()), "102052606221W500")
        self.assertEqual((z.group(1), z.group(2)), ("2", "1"))
        self.assertEqual((s.group(1), s.group(2), s.group(3)), ("May", "31", "2019"))


class Colours(unittest.TestCase):

    def test_a_span_colour_is_the_stroke_triple(self):
        self.assertEqual(bj1._rgb(0x0000FF), (0.0, 0.0, 1.0))
        self.assertEqual(bj1._rgb(0xFF8000), (1.0, 0.5, 0.0))
        self.assertEqual(bj1._rgb(None), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
