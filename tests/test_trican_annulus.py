"""Trican layout A draws SIX curves; the reader claimed five.

  python3 -m unittest tests.test_trican_annulus

"Annulus Pressure (kPa)" is in the legend of every layout-A chart and had no
rule of its own. That was not simply a missing channel: orange satisfies the
maroon test — (156,72,0) has r < 190, r-g = 84, r-b = 156 — so the annulus
trace was being collected as BOTTOM-HOLE pressure, and its brighter blends
were landing in Surface Pressure. Measured on 00233 p48, 409 of the 6,709
pixels claimed as bh were orange.

Checked against the answer key this template ships: the STAGE INFORMATION
table on the very next page prints the Surface Pressure Maximum per stage.
Before, our maxima ran 8 to 11 MPa above it; after, they land within 0.2.

Maroon and bright red both sit on the red axis with g and b together; orange
does not. g - b is the whole separation and it is wide: 0 for (116,0,0) and
(255,0,0), 116 for (191,116,0). These tests pin that boundary.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import trican_charts as tc


def who(rgb):
    """Which series masks claim a single pixel of this colour."""
    img = np.array([[list(rgb)]])
    return sorted(k for k, v in tc.series_masks(img).items() if v[0][0])


class OneColourOneSeries(unittest.TestCase):
    def test_the_template_palette_each_lands_in_exactly_one(self):
        for rgb, want in (((116, 0, 0), "bh"),
                          ((255, 0, 0), "surface"),
                          ((191, 116, 0), "annulus"),
                          ((0, 116, 191), "rate"),
                          ((34, 139, 34), "wh_conc"),
                          ((154, 205, 50), "dh_conc")):
            self.assertEqual(who(rgb), [want], f"rgb{rgb}")

    def test_the_orange_that_was_being_read_as_bottom_hole(self):
        # 407 of the 409 contaminating pixels on 00233 p48 were this colour
        self.assertEqual(who((156, 72, 0)), ["annulus"])

    def test_the_orange_red_that_was_being_read_as_surface(self):
        self.assertEqual(who((255, 69, 0)), ["annulus"])

    def test_a_maroon_blend_is_never_taken_for_the_annulus(self):
        # A maroon/white blend keeps g == b, and that is the whole separation.
        # It stays with bh while it is dark; past r = 200 the existing rules
        # hand it to surface, which is this template's documented behaviour
        # ("blends stay at r=255") and not something this change touches. What
        # must never happen is it being read as the annulus.
        for k in (20, 40, 60):
            rgb = (116 + k, k, k)
            self.assertEqual(who(rgb), ["bh"], f"rgb{rgb}")
        for k in (80, 100, 120):
            rgb = (116 + k, k, k)
            self.assertNotIn("annulus", who(rgb), f"rgb{rgb}")

    def test_a_bright_red_blend_is_never_taken_for_the_annulus(self):
        for k in (20, 60, 100):
            rgb = (255, k, k)
            self.assertIn("surface", who(rgb), f"rgb{rgb}")
            self.assertNotIn("annulus", who(rgb), f"rgb{rgb}")

    def test_nothing_is_claimed_twice(self):
        for rgb in ((116, 0, 0), (255, 0, 0), (191, 116, 0), (156, 72, 0),
                    (255, 69, 0), (0, 116, 191), (34, 139, 34), (154, 205, 50)):
            self.assertLessEqual(len(who(rgb)), 1, f"rgb{rgb} claimed twice")

    def test_white_and_grey_are_claimed_by_nothing(self):
        for rgb in ((255, 255, 255), (211, 211, 211), (128, 128, 128), (0, 0, 0)):
            self.assertEqual(who(rgb), [], f"rgb{rgb}")


class SeriesList(unittest.TestCase):
    def test_annulus_is_declared_and_read_on_the_pressure_axis(self):
        keys = [s[0] for s in tc.SERIES]
        self.assertIn("annulus", keys)
        row = next(s for s in tc.SERIES if s[0] == "annulus")
        self.assertEqual(row[1], "Annulus Pressure")
        self.assertEqual(row[3], "press")      # left axis, like the other two
        self.assertEqual(row[4], 1.0)          # not a 100x concentration

    def test_the_five_that_were_already_there_are_untouched(self):
        keys = [s[0] for s in tc.SERIES]
        for k in ("bh", "surface", "rate", "wh_conc", "dh_conc"):
            self.assertIn(k, keys)


if __name__ == "__main__":
    unittest.main()
