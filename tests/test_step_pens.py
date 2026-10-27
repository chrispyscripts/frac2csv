"""STEP pens that are drawn on the page and were not read.

00196-00201 print an "Offset Analysis" chart per stage whose legend, UNDER
the plot, names seven neighbouring wells' casing pressures on the one
pressure axis (00196 p19): only the red was read. The coil-tubing stages
(00243 p77, 00198 p75) draw the coil's pressure in yellow, which no colour
table named. 00241 p84/p85 print the offset and chemical charts under each
other's bars.

  python3 -m unittest tests.test_step_pens
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import step1                                             # noqa: E402

RED, BLUE, YELLOW = (250, 0, 0), (25, 98, 255), (255, 243, 1)
GREY, MAGENTA, ORANGE = (135, 135, 135), (242, 33, 189), (245, 189, 40)
CYAN, GREEN = (119, 255, 255), (46, 254, 0)


def page_with_legend(colours, box=(60, 20, 560, 320)):
    """A white chart image with an empty frame `box` and, under it, a column
    of 9 px swatches 15 px apart, each followed by a block of dark "text"."""
    img = np.full((520, 640, 3), 255, int)
    x0, y0, x1, y1 = box
    img[y0, x0:x1] = img[y1, x0:x1] = 0
    img[y0:y1, x0] = img[y0:y1, x1] = 0
    for k, rgb in enumerate(colours):
        top = y1 + 45 + 15 * k
        img[top:top + 9, 70:79] = rgb
        img[top + 1:top + 8, 90:200:3] = 60          # text: dark strokes
    return img, box


class CasingLegend(unittest.TestCase):
    def read(self, colours, lines):
        img, box = page_with_legend(colours)
        with mock.patch.object(step1.ar, "ocr_line", side_effect=list(lines)):
            return step1._casing_legend(img, box)

    def test_the_wells_under_the_plot_are_named_from_their_lines(self):
        got = self.read([RED, BLUE, YELLOW, GREY, CYAN],
                        ["SURFACE Main (MPa)", "E Well Casing (MPs)",
                         "B Well Casing (MPa)", "A Well Casing (MP3)",
                         "B well lower pop valve (MPa}"])
        self.assertEqual([e["label"] for e in got],
                         ["E Well Casing Pressure", "B Well Casing Pressure",
                          "A Well Casing Pressure", "B Well Lower Pop Valve Pressure"])
        # the swatch's own colour, from its middle
        self.assertLess(np.abs(np.asarray(got[0]["rgb"]) - BLUE).max(), 2)
        self.assertLess(np.abs(np.asarray(got[2]["rgb"]) - GREY).max(), 2)

    def test_an_o_read_as_a_zero_is_put_back(self):
        got = self.read([RED, BLUE, ORANGE],
                        ["SURFACE Main (MPa)", "E Well Casing (MPa)",
                         "0 Well Casing (MPa)"])
        self.assertEqual(got[1]["label"], "O Well Casing Pressure")

    def test_one_well_is_not_an_offset_chart(self):
        self.assertEqual(self.read([RED, BLUE, GREEN],
                                   ["SURFACE Main (MPa)", "E Well Casing (MPa)",
                                    "Prop Conc (kg/m3)"]), [])

    def test_a_treatment_legend_is_never_read(self):
        # two swatches a column, as 00196 p18 prints them: no OCR at all
        img, box = page_with_legend([RED, BLUE])
        with mock.patch.object(step1.ar, "ocr_line") as ocr:
            self.assertEqual(step1._casing_legend(img, box), [])
            ocr.assert_not_called()


class SwatchFamily(unittest.TestCase):
    def test_families(self):
        self.assertEqual(step1._swatch_family(RED), "red")
        self.assertEqual(step1._swatch_family(BLUE), "blue")
        self.assertEqual(step1._swatch_family(ORANGE), "orange")
        self.assertEqual(step1._swatch_family(CYAN), "cyan")

    def test_magenta_passes_the_red_rule_too_and_is_magenta(self):
        self.assertEqual(step1._swatch_family(MAGENTA), "magenta")

    def test_yellow_and_grey_are_no_family(self):
        self.assertIsNone(step1._swatch_family(YELLOW))
        self.assertIsNone(step1._swatch_family(GREY))


class CasingMasks(unittest.TestCase):
    def plot(self):
        img = np.full((200, 300, 3), 255, int)
        box = (0, 0, 300, 200)
        img[:, 150] = 0                                  # a black gridline
        img[:, 149] = img[:, 151] = (140, 140, 140)       # ...and its blurred edge
        img[40:42, :] = GREY                              # A Well
        img[100:102, :] = (240, 226, 101)                 # B Well, yellow
        img[60:62, :] = (206, 211, 67)                    # green over orange: dull
        img[150:152, :] = BLUE
        img[152, :] = (122, 131, 162)                     # blue on orange: grey
        img[153:155, :] = ORANGE
        return img, box

    def test_grey_and_yellow_pens(self):
        img, box = self.plot()
        legend = [{"rgb": GREY, "label": "A"}, {"rgb": YELLOW, "label": "B"}]
        masks = step1.ar.hue_masks(img)
        grey, yel = step1._casing_masks(img, box, legend, masks)
        rows = np.flatnonzero(grey.any(axis=1))
        self.assertEqual(sorted(set(rows)), [40, 41])
        # the gridline's grey edge is not the pen
        self.assertFalse(grey[:, 149].any() or grey[:, 151].any())
        self.assertEqual(sorted(set(np.flatnonzero(yel.any(axis=1)))), [100, 101])


class CoilLegend(unittest.TestCase):
    def test_wordings(self):
        for t in ("Coil Pressure (MPa)", "Coe Pressure (MPa)",
                  "COIL #1 CIRCULATING PRESSURE"):
            self.assertTrue(step1._COIL.search(t), t)
        for t in ("C Well Casing Pressure", "Combined Slurry Rate (m3/min)",
                  "Surface Main (MPa)", "COIL #1 FLUID RATE"):
            self.assertFalse(step1._COIL.search(t), t)


class BarTag(unittest.TestCase):
    def test_an_offset_chart_under_the_chemical_bar_is_the_offset_chart(self):
        chans = [{"label": "Surface Pressure", "unit": "MPa"},
                 {"label": "B Well Offset Pressure", "unit": "MPa",
                  "offset": {"group": "offset"}}]
        self.assertEqual(step1._bar_tag("c", "", chans), ("t", None))

    def test_a_chemical_chart_under_the_offset_bar_is_chemical(self):
        tag, note = step1._bar_tag(
            "t", "shell canada limited offset analysis treatment 31",
            [{"label": "Slurry Rate", "unit": "m3/min"}])
        self.assertEqual(tag, "c")
        self.assertTrue(note)

    def test_an_offset_chart_with_its_pressure_stays(self):
        self.assertEqual(step1._bar_tag(
            "t", "shell canada limited offset analysis",
            [{"label": "Surface Pressure", "unit": "MPa"}]), ("t", None))


class SideBySide(unittest.TestCase):
    def page(self, panels):
        img = np.full((600, 900, 3), 255, int)
        w = 860 // panels
        for k in range(panels):
            for y in range(100, 500, 80):              # five gridlines
                img[y, 20 + k * w + 10:20 + (k + 1) * w - 40] = 0
        return img

    def test_three_panels_in_a_row(self):
        # 00241 p24: Treatment 1's three attempts, a third of the width each
        self.assertGreaterEqual(step1._side_by_side(self.page(3)), 2)

    def test_an_ordinary_chart_is_one(self):
        self.assertEqual(step1._side_by_side(self.page(1)), 1)


if __name__ == "__main__":
    unittest.main()
