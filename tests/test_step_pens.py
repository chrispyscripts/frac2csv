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

    def test_an_a_read_as_s(self):
        # 00198 p21
        got = self.read([RED, BLUE, CYAN],
                        ["SURFACE Msin (MPa)", "E Well Cssing (MPs)",
                         "B well lower pop vsive (MPs)"])
        self.assertEqual([e["label"] for e in got],
                         ["E Well Casing Pressure", "B Well Lower Pop Valve Pressure"])

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


class LegendUnit(unittest.TestCase):
    def test_a_concentration_is_not_in_kpa(self):
        # 00247 p23: "Prop Conc (kg/m3)" read as kPa
        self.assertEqual(step1._legend_unit_for("Prop Conc", "kPa"), "kg/m3")
        self.assertEqual(step1._legend_unit_for("Surf Total Proppant Conc", "MPa"), "")

    def test_units_that_agree_stand(self):
        self.assertEqual(step1._legend_unit_for("Surface Pressure", "MPa"), "MPa")
        self.assertEqual(step1._legend_unit_for("Combined Slurry Rate", "m3/min"), "m3/min")
        self.assertEqual(step1._legend_unit_for("Aqucar 742 Conc", "L/m3"), "L/m3")


class LabelOnTheOtherSide(unittest.TestCase):
    def test_a_laddered_family_gives_a_close_label_to_the_runner_up(self):
        # 00247 p23: dark green labels on the right counted as cyan, whose
        # ladder is on the left
        img = np.full((300, 200, 3), 255, int)
        masks = {"cyan": np.zeros((300, 200), bool), "green": np.zeros((300, 200), bool)}
        masks["cyan"][95:105, 150:170] = True
        masks["green"][97:104, 150:166] = True
        out = {"cyan": [(16.0, 10, True), (8.0, 100, True), (0.0, 190, True)], "green": []}
        words = [("1600", (160 - 140) * 3, 100 * 3)]
        with mock.patch.object(step1.ar, "ocr_words", return_value=words):
            got = step1.ar.ocr_tick_strip(img, masks, 140, 200, out=dict(
                (k, list(v)) for k, v in out.items()), in_strip=True)
        self.assertIn((1600.0, 100, True), got["green"])
        with mock.patch.object(step1.ar, "ocr_words", return_value=words):
            got = step1.ar.ocr_tick_strip(img, masks, 140, 200, out=dict(
                (k, list(v)) for k, v in out.items()))
        self.assertIn((1600.0, 100, True), got["cyan"])


class BlankBody(unittest.TestCase):
    def test_a_blank_chart_area(self):
        # 00270 p30: title, interval and info table round a blank chart area
        img = np.full((1000, 800, 3), 255, int)
        img[50:60, 100:700] = (200, 90, 40)
        img[900:950, 100:700] = 0
        self.assertTrue(step1._blank_body(img))
        img[300, 150:650] = 0                             # a gridline
        img[200:340, 400] = (250, 0, 0)                   # a curve
        self.assertFalse(step1._blank_body(img))


class PaleTitles(unittest.TestCase):
    def test_the_left_takes_pressure_only(self):
        rows = np.full((50, 60, 3), 255, int)
        got = [("rate", 10), ("pressure", 40)]
        with mock.patch.object(step1.ar, "read_axis_titles", return_value=got):
            self.assertEqual(step1._pale_titles(rows, 0, 60, ccw=False, only="pressure"),
                             [("pressure", 40)])
            self.assertEqual(step1._pale_titles(rows, 0, 60, ccw=True), got)

    def test_a_chemical_title_is_not_taken_on_the_left(self):
        rows = np.full((50, 60, 3), 255, int)
        with mock.patch.object(step1.ar, "read_axis_titles", return_value=[("rate", 10)]):
            self.assertEqual(step1._pale_titles(rows, 0, 60, ccw=False, only="pressure"), [])


class StageTitled(unittest.TestCase):
    def read(self, band, box_text):
        img = np.full((900, 700, 3), 255, int)
        words = [[(w, 0, 0) for w in band.split()], [(w, 0, 0) for w in box_text.split()]]
        meta = {"stage": None, "interval": "", "kind": "main"}
        with mock.patch.object(step1.ar, "ocr_words", side_effect=words):
            return step1._stage_titled_meta(img, (100, 300, 600, 500), meta)

    def test_00278(self):
        m = self.read("200/d-016-K/094-H-05 - Stage 1 3579.95 m - 3580.05 m",
                      "License 031988. Date 2/12/2017 Clean Flow Rate")
        self.assertEqual((m["stage"], m["interval"], m["date"]),
                         (1, "3579.95-3580.05 m", "2017-02-12"))

    def test_a_day_first_date(self):
        m = self.read("well - Stage 12", "Date 25/02/2017")
        self.assertEqual(m["date"], "2017-02-25")

    def test_a_treatment_title_is_left_alone(self):
        m = self.read("Shell Canada Limited Treatment Analysis Treatment 31", "")
        self.assertIsNone(m["stage"])
        self.assertNotIn("date", m)


class DistinctInliers(unittest.TestCase):
    def test_two_labels_read_twice_are_two(self):
        # 00272 p66: 15 / 12 read "45" / "42" by both page modes
        seg = [(45.0, 306, True), (42.0, 448, True)] * 2 + [(9.0, 590, True)]
        cal = step1.ar.fit_ticks_guarded(seg)
        self.assertIsNotNone(cal)
        self.assertLess(step1._distinct_inliers(seg, cal), 3)

    def test_a_ladder(self):
        seg = [(15.0, 306, True), (12.0, 448, True), (9.0, 590, True),
               (6.0, 733, True), (3.0, 876, True)]
        cal = step1.ar.fit_ticks_guarded(seg)
        self.assertEqual(step1._distinct_inliers(seg, cal), 5)


def T(pairs):
    return [(float(v), y, True) for v, y in pairs]


class LadderRepairs(unittest.TestCase):
    def test_a_lost_decimal_point(self):
        # 00208 p22: 10.000 / 7.500 / 5.000 / 2.500 / 0.0 read 10.0, 7500 ...
        pts = T([(10, 1395), (7500, 1568), (5000, 1742), (2500, 1916), (0, 2088)])
        a, b, _n = step1._fit(pts)
        self.assertAlmostEqual(a + b * 1395, 10.0, delta=0.2)
        self.assertAlmostEqual(a + b * 2088, 0.0, delta=0.2)
        # not asked for, the line as read stands
        a, b, _n = step1.ar.fit_ticks_guarded(pts)
        self.assertGreater(a + b * 1395, 5000)

    def test_a_one_read_as_four(self):
        # 00272 p66: 15 / 12 read 45 / 42
        pts = T([(45, 306), (42, 448), (9, 590), (3, 876)]) * 2
        a, b, _n = step1._fit(pts)
        self.assertAlmostEqual(a + b * 306, 15.0, delta=0.3)

    def test_one_slipped_label_does_not_widen_the_tolerance(self):
        # 00186 p63: 80 / 64 / 48 / 3200 / 16 / 0 — the 0..80 line as read
        pts = T([(80, 327), (64, 461), (48, 594), (3200, 728), (16, 862), (0, 994)])
        a, b, _n = step1._fit(pts)
        self.assertAlmostEqual(a + b * 327, 80.0, delta=0.5)

    def test_a_good_ladder_is_left_alone(self):
        for pairs in ([(75, 306), (60, 448), (45, 590), (30, 733), (15, 876)],
                      [(1000, 306), (750, 484), (500, 662), (250, 840), (0, 1017)],
                      [(40, 306), (30, 484), (20, 662), (10, 840), (0, 1017)]):
            self.assertEqual(step1._fit(T(pairs)),
                             step1.ar.fit_ticks_guarded(T(pairs)))


class ChemicalTableNames(unittest.TestCase):
    def test_00278s_additives_are_not_00183s(self):
        band = lambda: "Clean Flow Rate (m3/min) SSl-1 @ 0.15 (L/m3) Econo @ 0.1 SCS-1 @ 0.8 SFR-106 0.8"
        for name in ("Aqucar 742 Conc", "SFR-202 B Conc", "SSI-3 Conc"):
            self.assertFalse(step1._table_name_ok("c", "red", name, {}, band))

    def test_the_books_that_print_them(self):
        band = lambda: "CLEAN RATE (m?/min) Agucar 742 Conc. SSI-3 Conc. $FR-202 Conc."
        for name in ("Aqucar 742 Conc", "SFR-202 B Conc", "SSI-3 Conc"):
            self.assertTrue(step1._table_name_ok("c", "red", name, {}, band))

    def test_a_band_the_ocr_could_not_read_says_nothing(self):
        band = lambda: "~~ —— eee ——"
        self.assertTrue(step1._table_name_ok("c", "red", "Aqucar 742 Conc", {}, band))

    def test_a_second_clean_rate(self):
        legend = {"blue": ("Clean Rate", "m3/min")}
        self.assertFalse(step1._table_name_ok("c", "cyan", "Combined Clean Rate",
                                              legend, lambda: ""))
        self.assertTrue(step1._table_name_ok("c", "cyan", "Combined Clean Rate",
                                             {"cyan": ("Clean Rate", "m3/min")}, lambda: ""))

    def test_the_surface_chart_is_not_asked(self):
        self.assertTrue(step1._table_name_ok("t", "red", "Surface Pressure", {}, lambda: ""))


class LegendEntries(unittest.TestCase):
    def test_names(self):
        cases = {"SFR-202 Conc. (L/m?)": ("SFR-202 Conc", "L/m3"),
                 "CHEM 1 RATE 1 Cone. (Lim?)": ("CHEM 1 RATE 1 Conc", "L/m3"),
                 "COMBINED CLEAN RATE (m/min)": ("Combined Clean Rate", "m3/min"),
                 "Aquear 742 Conc. (L/m*)": ("Aqucar 742 Conc", "L/m3"),
                 "CHEM 2 RATE 5 (Limin)": ("Chem 2 Rate 5", "L/min")}
        for raw, want in cases.items():
            self.assertEqual(step1._legend_entry_name(raw), want, raw)

    def test_headers(self):
        self.assertEqual(step1._header_qty("TP Rate (L/min)"), "tp")
        self.assertEqual(step1._header_qty("Clean Rate (m*/min)"), "rate")
        self.assertEqual(step1._header_qty("Chem Conc (L/m*)"), "conc")
        self.assertEqual(step1._header_qty("Pressure (MPa)"), "pressure")


class LeftRuleUnderAPen(unittest.TestCase):
    def test_00241_p94(self):
        # the left rule hidden over its top third by a pen drawn down it
        img = np.full((1300, 1800, 3), 255, int)
        img[300:1000, 1500] = 0                        # right rule
        img[500:1000, 250] = 0                         # left rule, top hidden
        img[300:1000, 250] = (240, 230, 40)
        img[500:1000, 250] = 0
        img[999, 250:1501] = 0                         # floor
        img[300, 250:1501] = 0
        img[360:660, 480] = 0                          # a curve's drop
        boxes = step1.find_charts(img)
        self.assertTrue(boxes)
        self.assertEqual(boxes[0][0], 250)


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
