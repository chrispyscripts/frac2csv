"""STEP's colour-keyed chemical charts, named and traced from their own legend.

00184's chemical charts exported the clean rate alone, on a 0..2100 axis
(380..1600 m3/min), and none of their four additives; 00278 dosed five
additives no colour table knew and exported them as "Series (x)", three pens
traced as one "magenta"; 00247 p107 printed SSI-LDP2 in the dark red the
table calls Aqucar 742; 00247 p25 printed the treatment chart's legend over
its additives.

  python3 -m unittest tests.test_step_chem_legend
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import auto_raster as ar                                 # noqa: E402
import pipeline                                          # noqa: E402
import step1                                             # noqa: E402


def blank(h=300, w=400):
    return np.full((h, w, 3), 255, np.uint8)


class TitledReaderRefusesInkedLadders(unittest.TestCase):
    """00184's three left ladders printed cyan, magenta and orange: the rotated
    OCR of their digits read "erate", the titled reader took the column for
    one rate axis and fitted 0..2100."""

    BOX = (150, 20, 390, 280)

    def ladder(self, colours):
        img = blank()
        for i, rgb in enumerate(colours):
            for k in range(6):
                y = 30 + 45 * k + 12 * i
                img[y:y + 6, 60:110] = rgb
        return img

    def test_warm_and_cool_ladders_are_colour_keyed(self):
        img = self.ladder([(0, 255, 255), (255, 0, 255), (255, 128, 0)])
        self.assertTrue(step1._ticks_in_pen_colours(img, self.BOX))

    def test_one_brown_ladder_is_not(self):
        # 00241, 00269-00274: one brown ladder under a rotated title
        img = self.ladder([(150, 75, 40)])
        self.assertFalse(step1._ticks_in_pen_colours(img, self.BOX))

    def test_black_ladders_are_not(self):
        img = self.ladder([(0, 0, 0), (40, 40, 40)])
        self.assertFalse(step1._ticks_in_pen_colours(img, self.BOX))

    def test_the_titled_reader_says_so(self):
        img = self.ladder([(0, 255, 255), (255, 128, 0)])
        with self.assertRaises(ValueError) as e:
            step1._extract_new_chart(img, box=self.BOX, require_titles=True)
        self.assertIn("colours", str(e.exception))


class LegendLines(unittest.TestCase):
    def test_names_and_units(self):
        cases = {
            "COMBINED CLEAN RATE (m?*/min)": ("Combined Clean Rate", "m3/min"),
            "SSI-LDP2 Conc. {L/m*}": ("SSI-LDP2 Conc", "L/m3"),
            "Chem Rate 6 Conc. (L/m*)": ("Chem Rate 6 Conc", "L/m3"),
            # the design dose is not part of the pen's name; "(" read as "i"
            "Econo @ 0.1 iLim*}": ("Econo Conc", "L/m3"),
            "SFE-2 @ 1.0 {L/m*)": ("SFE-2 Conc", "L/m3"),
            "Clean Flow Rate (m/min)": ("Clean Rate", "m3/min"),
            "AQUCAR 742 Conc. (L/m3)": ("Aqucar 742 Conc", "L/m3"),
        }
        for text, want in cases.items():
            self.assertEqual(step1._chem_legend_name(text), want, text)

    def test_unreadable_lines_are_no_opinion(self):
        self.assertIsNone(step1._chem_legend_name("~~ ="))
        self.assertIsNone(step1._chem_legend_name("Qx 7"))   # no unit, no vocabulary


class ReadByLegend(unittest.TestCase):
    def entries(self, *texts):
        return [{"rgb": np.array(rgb, float), "text": t}
                for t, rgb in zip(texts, [(0, 255, 255), (255, 0, 255),
                                          (128, 0, 0), (0, 255, 0)])]

    def test_a_treatment_legend_is_said_and_not_used(self):
        # 00247 p25
        ents = self.entries("Surface Pressure (MPa)", "COMBINED SLURRY RATE (m3/min)",
                            "Prop Conc (kg/m3)", "Btm Prop Conc (kg/m3)")
        with mock.patch.object(step1, "_legend_above", return_value=ents):
            self.assertEqual(step1._read_by_legend(blank(), (10, 10, 390, 290), 1.0),
                             ("treatment", None))

    def test_an_entry_that_did_not_read_leaves_it_to_the_table(self):
        ents = self.entries("COMBINED CLEAN RATE (m3/min)", "~~", "Aqucar 742 Conc. (L/m3)")
        with mock.patch.object(step1, "_legend_above", return_value=ents):
            self.assertEqual(step1._read_by_legend(blank(), (10, 10, 390, 290), 1.0),
                             (None, None))

    def test_an_offset_legend_is_not_a_chemical_one(self):
        ents = self.entries("A Well (MPa)", "B Well (MPa)")
        with mock.patch.object(step1, "_legend_above", return_value=ents):
            self.assertEqual(step1._read_by_legend(blank(), (10, 10, 390, 290), 1.0),
                             (None, None))

    def test_a_ladder_no_legend_pen_owns_refuses_the_legend(self):
        # 00269 p78: the light green SFR-202a's dashed entry did not read
        ents = self.entries("COMBINED CLEAN RATE (m3/min)", "SSI-LDP2 Conc. (L/m3)")
        img = blank()
        img[100:103, 60:110] = (0, 255, 255)       # each pen's ladder inked
        img[150:153, 60:110] = (255, 0, 255)
        fake = (np.arange(10.0), [{"key": "series-p0", "values": np.zeros(10)}],
                {"unowned_ticks": 6, "notes": []})
        with mock.patch.object(step1, "_legend_above", return_value=ents), \
                mock.patch.object(ar, "extract", return_value=fake):
            self.assertEqual(step1._read_by_legend(img, (150, 20, 390, 280), 1.0),
                             (None, None))


class PensByLegendColour(unittest.TestCase):
    """00278 p60: SSI-1 magenta, SCS-1 violet (142,0,255), Econo maroon
    (128,0,64) — the hue families put all three in "magenta"."""

    def test_each_pen_its_own_ink(self):
        img = blank()
        img[100:103, 20:380] = (255, 0, 255)
        img[150:153, 20:380] = (142, 0, 255)
        img[200:203, 20:380] = (128, 0, 64)
        img[150, 20:380] = (200, 150, 255)       # a paled edge
        legend = [(255, 43, 255), (147, 43, 255), (161, 45, 95)]
        masks, pens = step1._legend_masks(img, (10, 10, 390, 290), legend)
        self.assertEqual(sorted(masks), ["p0", "p1", "p2"])
        for key, row in (("p0", 101), ("p1", 151), ("p2", 201)):
            ys = np.nonzero(masks[key][:, 200])[0]
            self.assertTrue(len(ys) and abs(ys.mean() - row) <= 1.5, (key, ys))
        # the colours moved onto the plot's own ink
        self.assertEqual(pens[2], (128, 0, 64))

    def test_pens_too_alike_are_refused(self):
        img = blank()
        img[100:103, 20:380] = (255, 0, 255)
        self.assertIsNone(step1._legend_masks(img, (10, 10, 390, 290),
                                              [(255, 0, 255), (250, 10, 250)]))


class TickLabels(unittest.TestCase):
    def test_a_leading_zero_is_a_lost_point(self):
        self.assertEqual(ar._tick_value("08-"), "0.8")
        self.assertEqual(ar._tick_value("00"), "0.0")
        self.assertEqual(ar._tick_value("10-"), "10")
        self.assertEqual(ar._tick_value("0.2-"), "0.2")
        self.assertEqual(ar._tick_value("120"), "120")
        self.assertIsNone(ar._tick_value("1a"))

    def test_a_label_goes_to_the_pen_its_core_is_printed_in(self):
        # 00278 p52's dark green "3.000", whose glyph edges are teal and
        # cream: by pixel count it went to the blue pen
        patch = np.full((11, 41, 3), 255, np.uint8)
        patch[2:9, 6:34] = (240, 224, 176)       # cream edges, 196 - 112
        patch[3:8, 6:12] = (32, 176, 208)        # teal edges, 30
        patch[3:8, 30:34] = (96, 208, 240)       # and 20
        patch[3:7, 12:30] = (0, 128, 64)         # the ink itself, 72
        pal = {"p0": (0, 128, 192), "p2": (255, 128, 64), "p5": (0, 128, 64)}
        self.assertEqual(ar._label_pen(patch, pal), "p5")

    def test_a_ladder_printed_to_fewer_places_than_its_steps(self):
        # 00278 p70: 1.00/0.75/0.50/0.25/0.00 prints 1.0, 0.8, 0.5, 0.3, 0.0
        # (the maroon top label read "10", the violet one "4.0")
        for top in (1.0, 10.0, 4.0):
            pts = [(top, 1418, True), (0.8, 1589, True), (0.5, 1757, True),
                   (0.3, 1926, True), (0.0, 2095, True)]
            fit = ar.fit_ticks_guarded(pts, repairs=True)
            self.assertIsNotNone(fit, top)
            a, b, _n = fit
            self.assertAlmostEqual(a + b * 1418, 1.0, places=2)
            self.assertAlmostEqual(a + b * 2095, 0.0, places=2)

    def test_three_stacked_ladders_keep_their_fit(self):
        # 00247 p70's offset wells, 0..30 three times over, two labels read
        # without their point: offered at a tenth, they made a 0..3 ladder
        pts = [(30.0, 383, True), (30.0, 395, True), (30.0, 411, True),
               (22.5, 546, True), (2250.0, 555, True), (22.5, 573, True),
               (15.0, 708, True), (15.0, 718, True), (15.0, 735, True),
               (7.5, 870, True), (7500.0, 881, True), (7.5, 897, True),
               (0.0, 1033, True), (0.0, 1041, True), (0.0, 1060, True)]
        a, b, _n = ar.fit_ticks_guarded(pts, repairs=True)
        self.assertAlmostEqual(a + b * 395, 30.0, delta=0.6)

    def test_a_ladder_that_fits_is_not_rounded(self):
        # 00273 p45: 15..3 exact, 0 unread, a stray "55" under the frame
        pts = [(3.0, 876, True), (6.0, 732, True), (9.0, 590, True), (12.0, 448, True),
               (15.0, 306, True), (42.0, 448, True), (45.0, 306, True), (55.0, 1029, True)]
        a, b, _n = ar.fit_ticks_guarded(pts, repairs=True)
        self.assertAlmostEqual(a + b * 1018, 0.0, delta=0.1)

    def test_three_exact_labels_beat_a_stray_at_a_tenth(self):
        # 00198 p41's rate ladder 16, 12, (8), 4, 0: the 8 unread, the 0 read
        # "5" and "55". 55 offered as 0.55 went out on 16..1
        pts = [(16.0, 23, True), (16.0, 23, True), (12.0, 203, True), (12.0, 203, True),
               (4.0, 563, True), (5.0, 749, True), (55.0, 755, True)]
        a, b, _n = ar.fit_ticks_guarded(pts, repairs=True)
        self.assertAlmostEqual(a + b * 743, 0.0, delta=0.05)
        # 00201 p95's 5, 4, 3, (2), 1, 0: the 1 read "4", the 0 "30" twice;
        # no line holds four, and 30 offered as 0.3 went out on 5..0.5
        pts = [(5.0, 23, True), (4.0, 167, True), (3.0, 311, True), (4.0, 599, True),
               (30.0, 749, True), (30.0, 755, True)]
        fit = ar.fit_ticks_guarded(pts, repairs=True)
        if fit:
            a, b, _n = fit
            self.assertAlmostEqual(a + b * 743, 0.0, delta=0.05)

    def test_an_exact_ladder_keeps_its_own_fit(self):
        pts = [(v, 100 + 50 * k, True) for k, v in enumerate((10, 8, 6, 4, 2, 0))]
        a, b, n = ar.fit_ticks_guarded(pts, repairs=True)
        self.assertEqual(n, 6)
        self.assertAlmostEqual(a + b * 100, 10.0, places=6)


def chem(page, pens, frames, legend):
    data = {k: np.ones(5) for k in pens}
    return {"type": "series", "source": "STEP chemical chart (raster)", "page": page,
            "meta": {"stage": str(page)}, "data": data,
            "units": {k: ("m3/min" if "Rate" in k else "L/m3" if "Conc" in k else "")
                      for k in pens},
            "scales": dict(frames), "frames": dict(frames), "deduced": {},
            "labels": {}, "chem_pens": dict(pens), "chem_legend": legend}


class BorrowedNames(unittest.TestCase):
    """00247 p25 prints the treatment legend; p27, a stage on, its own."""

    RED, GREEN, MAGENTA, CYAN = (128, 0, 0), (0, 255, 0), (255, 0, 255), (0, 255, 255)

    def test_the_next_chart_names_its_pens(self):
        p25 = chem(25, {"Series (red)": self.RED, "Series (green)": self.GREEN,
                        "Series (magenta)": self.MAGENTA, "Combined Clean Rate": self.CYAN},
                   {"Series (red)": (1.0, 0.0), "Series (green)": (2.0, 0.0),
                    "Series (magenta)": (1.0, 0.0), "Combined Clean Rate": (10.0, 0.0)},
                   "treatment")
        p27 = chem(27, {"Aqucar 742 Conc": (130, 4, 2), "SFR-202 B Conc": self.GREEN,
                        "SSI-3 Conc": self.MAGENTA, "Combined Clean Rate": self.CYAN},
                   {"Aqucar 742 Conc": (1.0, 0.0), "SFR-202 B Conc": (2.0, 0.0),
                    "SSI-3 Conc": (1.0, 0.0), "Combined Clean Rate": (10.0, 0.0)},
                   "read")
        p99 = chem(99, {"SSI-LDP2 Conc": self.RED}, {"SSI-LDP2 Conc": (1.0, 0.0)}, "read")
        notes = []
        pipeline._step_chem_names_borrowed([p25, p27, p99], notes)
        self.assertEqual(sorted(p25["data"]), ["Aqucar 742 Conc", "Combined Clean Rate",
                                               "SFR-202 B Conc", "SSI-3 Conc"])
        self.assertEqual(p25["units"]["Aqucar 742 Conc"], "L/m3")
        self.assertIn("Aqucar 742 Conc", p25["frames"])
        self.assertTrue(notes)
        self.assertTrue(all("chem_pens" not in r and "chem_legend" not in r
                            for r in (p25, p27, p99)))

    def test_a_pen_on_another_axis_is_not_the_same_pen(self):
        p25 = chem(25, {"Series (green)": self.GREEN}, {"Series (green)": (1.0, 0.0)},
                   "treatment")
        p27 = chem(27, {"SFR-202 B Conc": self.GREEN}, {"SFR-202 B Conc": (2.0, 0.0)},
                   "read")
        pipeline._step_chem_names_borrowed([p25, p27], [])
        self.assertIn("Series (green)", p25["data"])

    def test_no_lender_no_names(self):
        p25 = chem(25, {"Series (red)": self.RED}, {"Series (red)": (1.0, 0.0)},
                   "treatment")
        pipeline._step_chem_names_borrowed([p25], [])
        self.assertIn("Series (red)", p25["data"])


def plot(kind, n, labels):
    md = {"title": "Interval 4", "stage": "4", "date": "2017-04-10",
          "start_time": "06:49:12", "duration_min": n / 60.0, "warnings": []}
    r = pipeline._series(md, np.arange(n, dtype=float),
                         {k: np.ones(n) for k in labels},
                         f"STEP {kind} chart (raster)", page=24)
    r["axis_t0_s"] = 0.0
    return r


class PageTwinCut(unittest.TestCase):
    """00184: once its chemical plots read five pens they outnumbered the
    surface plots' four and led the page. Stage 9's chemical chain settled
    21 min from the surface chain and moved the surface plot over stage 8;
    p24's chemical cut took 9.7 min of pumping the surface chain had kept."""

    def run_twins(self, surf_cut, chem_cut, pumped=False):
        surf = plot("surface", 5488, ["Surface Pressure", "Slurry Rate"])
        chem = plot("chemical", 4909, ["SSI-3 Conc", "Combined Clean Rate"])
        chem["handover"] = {"to": "5", "samples": np.arange(10.0), "data": {}}
        per = {"s": [(None, surf)], "c": [(None, chem)]}
        placed = {id(surf): 0, id(chem): 0}
        axis0 = {id(surf): 0.0, id(chem): 0.0}
        cuts = {id(chem): chem_cut}
        if surf_cut:
            cuts[id(surf)] = surf_cut
        pipeline._align_page_plots(per, placed, axis0, {}, cuts, [], [], [],
                                   pumped={id(surf)} if pumped else ())
        return len(surf["samples"])

    def test_a_surface_plot_cut_by_its_samples_is_not_cut_by_more_pens(self):
        self.assertEqual(self.run_twins(4, 5), 5488)

    def test_nor_one_carried_to_the_end_of_its_pumping(self):
        self.assertEqual(self.run_twins(0.5, 5, pumped=True), 5488)

    def test_a_surface_plot_cut_by_its_axes_alone_follows_the_samples(self):
        self.assertEqual(self.run_twins(0.5, 5), 4909)
        self.assertEqual(self.run_twins(None, 5), 4909)

class OneSpellingPerPen(unittest.TestCase):
    MAROON, MAGENTA = (128, 0, 64), (255, 0, 255)

    def charts(self, odd, odd_rgb):
        rs = [chem(p, {"Econo Conc": self.MAROON, "SSI-3 Conc": self.MAGENTA},
                   {"Econo Conc": (1.0, 0.0), "SSI-3 Conc": (1.0, 0.0)}, "read")
              for p in range(52, 58)]
        rs.append(chem(60, {odd: odd_rgb}, {odd: (1.0, 0.0)}, "read"))
        return rs

    def test_a_misread_name_takes_the_files_spelling(self):
        # 00278: "Econe" once in 30
        rs = self.charts("Econe Conc", (130, 2, 66))
        notes = []
        pipeline._step_chem_names_borrowed(rs, notes)
        self.assertIn("Econo Conc", rs[-1]["data"])
        self.assertTrue(notes)

    def test_a_near_name_in_another_colour_is_another_pen(self):
        # SSI-1 is not SSI-3, whatever the spelling distance
        rs = self.charts("SSI-1 Conc", (128, 0, 255))
        pipeline._step_chem_names_borrowed(rs, [])
        self.assertIn("SSI-1 Conc", rs[-1]["data"])


if __name__ == "__main__":
    unittest.main()
