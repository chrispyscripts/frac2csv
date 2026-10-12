"""What the STEP titled reader clears from a pen's trace before it is read.

00244 p96 (Carmine, #814-#817): an in-plot legend swatch read as a spike, a
neighbouring pen's anti-aliased edge read as the curve's last reading, the
yellow coil pressure's blend read as Btm Prop Conc, and stray clusters of it
floating between readings on the floor. And 01289 p202 (#829): the dip a
pen draws and climbs back out of, which the notch filter took for one of
those contaminants.

  python3 -m unittest tests.test_step_cleanups
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import auto_raster as ar                                 # noqa: E402
import step1                                             # noqa: E402


class LegendSwatch(unittest.TestCase):
    def setUp(self):
        self.sub = np.zeros((100, 200), bool)
        self.sub[60:63, :] = True                        # the curve
        self.sub[10:18, 20:28] = True                    # an 8 px swatch
        self.dark = np.zeros((100, 200), bool)

    def test_a_swatch_with_its_label_beside_it_is_cleared(self):
        self.dark[10:18, 31:70] = True                   # the label's text
        out = step1._drop_legend_swatches(self.sub, self.dark)
        self.assertFalse(out[10:18, 20:28].any())
        self.assertTrue(out[60:63, :].all())

    def test_a_square_with_nothing_written_beside_it_is_kept(self):
        out = step1._drop_legend_swatches(self.sub, self.dark)
        self.assertTrue(out[10:18, 20:28].all())


class FringeBlips(unittest.TestCase):
    def test_a_lone_speck_after_the_curve_ends_is_dropped(self):
        H, W = 100, 120
        sub = np.zeros((H, W), bool)
        other = np.zeros((H, W), bool)
        py = np.full(W, np.nan)
        py[:40] = 50.0
        sub[49:52, :40] = True
        sub[80, 90] = True                               # one pixel, alone
        py[90] = 80.0
        out = step1._drop_fringe_blips(py, sub, other)
        self.assertTrue(np.isnan(out[90]))
        self.assertTrue(np.isfinite(out[:40]).all())

    def test_a_short_run_against_another_pen_with_no_curve_near_is_dropped(self):
        H, W = 100, 120
        sub = np.zeros((H, W), bool)
        other = np.zeros((H, W), bool)
        py = np.full(W, np.nan)
        py[:40] = 50.0
        sub[49:52, :40] = True
        sub[70, 80:84] = True                            # four columns, one row
        other[71:74, 70:100] = True                      # the other pen's line
        py[80:84] = 70.0
        out = step1._drop_fringe_blips(py, sub, other)
        self.assertTrue(np.isnan(out[80:84]).all())

    def test_the_same_run_beside_the_curve_is_kept(self):
        H, W = 100, 120
        sub = np.zeros((H, W), bool)
        other = np.zeros((H, W), bool)
        py = np.full(W, np.nan)
        py[:76] = 70.0
        sub[69:72, :76] = True
        sub[70, 80:84] = True
        other[71:74, 70:100] = True
        py[80:84] = 70.0
        out = step1._drop_fringe_blips(py, sub, other)
        self.assertTrue(np.isfinite(out[80:84]).all())


class SparseCurve(unittest.TestCase):
    def test_a_curve_read_only_in_specks_is_not_dropped_as_blips(self):
        # 00119 p183's chemical green: short runs, 5% of its chart, beside
        # another pen's ink
        H, W = 100, 400
        sub = np.zeros((H, W), bool)
        other = np.zeros((H, W), bool)
        other[51:54, :] = True
        py = np.full(W, np.nan)
        for c0 in range(10, W, 40):
            sub[50, c0:c0 + 3] = True
            py[c0:c0 + 3] = 50.0
        out = step1._drop_fringe_blips(py, sub, other)
        self.assertTrue(np.array_equal(np.isfinite(out), np.isfinite(py)))


class FloatingOrphans(unittest.TestCase):
    def setUp(self):
        self.H, self.W = 200, 200
        self.floor = self.H - 2

    def trace(self):
        sub = np.zeros((self.H, self.W), bool)
        py = np.full(self.W, np.nan)
        py[:60] = self.floor                             # on the floor
        sub[self.floor - 1:, :60] = True
        py[70:75] = 60.0                                 # a cluster in mid-air
        sub[59:62, 70:75] = True
        return sub, py

    def test_a_cluster_between_floor_and_floor_is_dropped(self):
        sub, py = self.trace()
        py[95:150] = self.floor
        sub[self.floor - 1:, 95:150] = True
        out = step1._drop_floating_orphans(py, sub)
        self.assertTrue(np.isnan(out[70:75]).all())
        self.assertTrue(np.isfinite(out[95:150]).all())

    def test_a_cluster_with_nothing_after_it_is_dropped(self):
        sub, py = self.trace()
        out = step1._drop_floating_orphans(py, sub)
        self.assertTrue(np.isnan(out[70:75]).all())

    def test_a_cluster_that_leads_into_a_real_curve_is_kept(self):
        sub, py = self.trace()
        py[80:150] = 60.0                                # the curve carries on
        sub[59:62, 80:150] = True
        out = step1._drop_floating_orphans(py, sub)
        self.assertTrue(np.isfinite(out[70:75]).all())


class YellowGate(unittest.TestCase):
    def test_without_a_yellow_pen_the_orange_is_left_alone(self):
        # 00862 p164: green beside orange blends to "yellow" along half an
        # hour, and judged as a pen the rule nibbled the orange into a saw
        img = np.full((60, 200, 3), 255, np.uint8)
        img[20:23, :] = (230, 140, 30)                   # orange
        img[23:25, :] = (235, 200, 60)                   # the blend
        img[25:28, :] = (40, 170, 60)                    # green
        masks = ar.hue_masks(img)
        before = masks["orange"].copy()
        out = step1._drop_yellow_red_blend(dict(masks), img, box=(0, 0, 200, 60))
        self.assertTrue(np.array_equal(out["orange"], before))


class YellowPenFlank(unittest.TestCase):
    """With a real yellow pen on the page, only the pens' own sandwich goes.

    The masks are given as the hue families gave them on those pages: their
    cut-offs adapt to how saturated a page is, so flat test colours would not
    land in the same families."""

    def page(self):
        img = np.full((120, 300, 3), 255, np.uint8)
        img[10:13, :] = (238, 243, 63)                   # the yellow pen
        z = np.zeros(img.shape[:2], bool)
        return img, {"orange": z.copy(), "red": z.copy(), "green": z.copy()}

    def test_a_tan_btm_prop_conc_pen_is_not_its_own_flank(self):
        # 00100 p173: (233,202,171) with a darker core (208,169,124), which
        # the families took for orange AND red
        img, m = self.page()
        img[60:62, :] = (233, 202, 171)
        img[62, :] = (208, 169, 124)
        img[63:65, :] = (233, 202, 171)
        m["orange"][60:65, :] = True
        m["red"][62:65, :] = True
        out = step1._drop_yellow_red_blend(dict(m), img, box=(0, 0, 300, 120))
        self.assertTrue(out["orange"][60:65].all())

    def test_the_blend_between_a_yellow_and_a_red_pen_goes(self):
        # 00244 p96 after the shutdown, as the page draws it
        img, m = self.page()
        img[80:83, :] = (224, 220, 86)                   # yellow
        img[83, :] = (128, 41, 0)                        # the dark blend
        img[84:86, :] = (166, 101, 79)                   # the red-brown pen
        m["orange"][83, :] = True
        m["red"][84:86, :] = True
        out = step1._drop_yellow_red_blend(dict(m), img, box=(0, 0, 300, 120))
        self.assertFalse(out["orange"][83].any())


class BracketedDip(unittest.TestCase):
    """01289 p202: 44 -> 27 MPa, 90 s flat, and back (#829)."""

    def dip(self):
        H, W = 300, 260
        sub = np.zeros((H, W), bool)
        sub[100:103, :120] = True                        # the pressure held
        sub[100:201, 120] = True                         # falls
        sub[198:201, 121:133] = True                     # flat at the bottom
        sub[100:201, 133] = True                         # climbs back
        sub[100:103, 134:] = True
        return sub

    def test_off_by_default_the_dip_is_still_a_notch(self):
        py = ar.curve_positions(self.dip())
        self.assertTrue(np.isnan(py[122:132]).all())

    def test_bracketed_the_flat_bottom_is_read(self):
        py = ar.curve_positions(self.dip(), bracketed=True)
        self.assertTrue(np.isfinite(py[121:133]).all())
        self.assertTrue(np.all(np.abs(py[122:132] - 199) <= 1))

    def test_a_stray_notch_with_no_stroke_into_it_is_still_dropped(self):
        sub = self.dip()
        sub[100:201, 120] = False                        # no fall
        sub[100:201, 133] = False                        # no climb
        sub[100:103, 120:134] = True
        sub[150:153, 60:66] = True                       # a contaminant below
        sub[100:103, 60:66] = False                      # where the curve is lost
        py = ar.curve_positions(sub, bracketed=True)
        self.assertTrue(np.isnan(py[60:66]).all())


if __name__ == "__main__":
    unittest.main()
