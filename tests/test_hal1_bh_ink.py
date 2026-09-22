"""Hal-1's purple BH Prop Conc does not read the crimson pressure pen (#702-#704).

Carmine reported the same fault three times against "Halliburton treatment plot
(raster)": 00413 chart 18 "BH prop con misbehaving on first half of x axis",
00413 chart 19 and 00423 chart 20 "prop con appears to overlap with TR pressure
data". Those are pages 247, 250 and 359 of

  AER-Frac-Montney-ARC/00413-100012606306W600_0503297_COMP.pdf
  AER-Frac-Montney-ARC/00423-100113306204W600_0503461_COMP.pdf

The colours below are read off those pages: Treating Pressure is drawn in a
crimson near (184, 27, 70) and Bottom-Hole Proppant Concentration in a purple
near (123, 67, 132). auto_raster's magenta rule only asks that blue beat GREEN,
so the crimson satisfies it too and half of each page's magenta mask was
pressure ink (3960 px of 8152 on p247, 3932 of 8362 on p250, 4229 of 8810 on
p359). Through the pad, where the bottom-hole pen still rests at zero — the
first 20 minutes of chart 18's 77 — the tracer had nothing else to follow and
exported the pressure curve at fifteen times its value, both axes being read
off the same two frame rows (1500.0..0.46 for conc, 100.0..0.07 for pressure):
BH Prop Conc peaked at 1139.69 kg/m3 on chart 18, where the purple pen
plateaus below 600.

Measured on those three charts, the share of samples reading ON the pressure
stroke over the first half of the record went 21.4/31.6/28.5% -> 0.0/0.0/0.0%,
and the peaks to 565.22/591.19/560.75 kg/m3.

  python3 -m unittest tests.test_hal1_bh_ink
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_raster as ar                                   # noqa: E402
import hal1                                                # noqa: E402

CRIMSON = (184, 27, 70)      # Treating Pressure, measured on 00413 p247
PURPLE = (123, 67, 132)      # Bottom-Hole Proppant Concentration, same page
H, W = 200, 400
PRESS_ROWS = slice(60, 63)   # the pressure pen, held high all across
FLOOR_ROWS = slice(190, 193)  # where the bottom-hole pen rests during the pad


def _bh_mask_fn():
    """The mask rule SERIES actually wires to BH Prop Conc."""
    return next(fn for label, _u, _a, fn in hal1.SERIES if label == "BH Prop Conc")


def chart():
    """Crimson high across the width; purple at the floor, then climbing.

    The shape of a real stage: bottom-hole concentration is zero until proppant
    reaches the perforations (the first 20 minutes of chart 18's 77), so over
    the left half the purple pen only rests on the axis.
    """
    img = np.full((H, W, 3), 255, int)
    img[PRESS_ROWS, :] = CRIMSON
    img[FLOOR_ROWS, 0:W // 2] = PURPLE
    for cx in range(W // 2, W):
        row = 191 - (cx - W // 2) // 2          # climbs away from the floor
        img[row:row + 3, cx] = PURPLE
    return img


class CrimsonIsNotMagenta(unittest.TestCase):

    def test_the_families_really_do_overlap(self):
        """The mechanism itself: one crimson pixel, two families."""
        masks = ar.hue_masks(chart())
        self.assertIsNotNone(masks.get("red"))
        self.assertIsNotNone(masks.get("magenta"))
        crimson = masks["magenta"][PRESS_ROWS]
        self.assertEqual(int(crimson.sum()), 3 * W)     # every pressure pixel
        self.assertEqual(int(masks["red"][PRESS_ROWS].sum()), 3 * W)

    def test_the_bh_mask_keeps_the_purple_and_drops_the_crimson(self):
        img = chart()
        masks = ar.hue_masks(img)
        mask = _bh_mask_fn()(masks, img[..., 1], img[..., 2])
        self.assertIsNotNone(mask)
        self.assertEqual(int(mask[PRESS_ROWS].sum()), 0)
        # the pad half of the purple pen is untouched
        self.assertEqual(int(mask[FLOOR_ROWS, 0:W // 2].sum()), 3 * (W // 2))

    def test_the_trace_follows_the_purple_pen_not_the_pressure(self):
        """What the client sees: the exported concentration's SHAPE.

        Handed the raw magenta mask the tracer settles on the crimson for every
        column — the whole record reads as the pressure curve, which is the
        "overlap with TR pressure data" of #703 and #704.
        """
        img = chart()
        masks = ar.hue_masks(img)
        raw = ar.curve_positions(masks["magenta"])
        self.assertLess(float(np.nanmedian(raw)), 70)          # on the crimson

        mask = _bh_mask_fn()(masks, img[..., 1], img[..., 2])
        got = ar.curve_positions(mask)
        self.assertTrue(np.isfinite(got[:W // 2]).all())
        self.assertTrue(np.allclose(got[:W // 2], 191.0))       # at the floor
        self.assertGreater(float(np.nanmin(got)), 90)           # never the pen above

    def test_a_page_with_no_red_family_still_reads(self):
        """hue_masks drops a family below its pixel floor; that is not a fault."""
        img = np.full((H, W, 3), 255, int)
        img[FLOOR_ROWS, :] = PURPLE
        masks = ar.hue_masks(img)
        self.assertIsNone(masks.get("red"))
        mask = _bh_mask_fn()(masks, img[..., 1], img[..., 2])
        self.assertEqual(int(mask.sum()), 3 * W)


if __name__ == "__main__":
    unittest.main()
