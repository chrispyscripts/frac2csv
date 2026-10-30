"""STEP pages that print one chart under another chart's legend or bar.

00247 p107 and p109 print stage 43's and 44's treatment charts under the
offset chart's legend, and the Prop Conc went out as "F Well Casing Pressure"
reading 501 MPa. 00269 p66 prints stage 19's offset chart under the "Offset
Analysis" bar below its chemical chart, and it was read as a second chemical
chart.

  python3 -m unittest tests.test_offset_misprints
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402
import step1                                             # noqa: E402


def pens(frames):
    return [{"key": f"series-{fam}", "label": f"Series ({fam})", "unit": "",
             "axis_frame": fr} for fam, fr in frames.items()]


# the legend the offset reader took off 00247 p107
P107_LEGEND = {"red": ("Surface Pressure", "MPa"),
               "green": ("O Well Casing Pressure", "MPa"),
               "cyan": ("A Well Casing Pressure", "MPa"),
               "orange": ("C Well Casing Pressure", "MPa"),
               "magenta": ("E Well Casing Pressure", "MPa")}


class WellsAxes(unittest.TestCase):
    def test_a_well_on_the_proppant_axis_is_the_wrong_legend(self):
        # 00247 p107: the treatment chart's own axes
        chans = pens({"red": (80.0, 0.0), "orange": (1600.0, 0.0),
                      "green": (1600.0, 0.0), "magenta": (1.6, 0.0),
                      "cyan": (16.0, 0.0)})
        self.assertFalse(step1._wells_axes(chans, P107_LEGEND))

    def test_an_offset_chart_keeps_its_wells(self):
        # 00247 p106: surface pressure on 0..80, every well on 0..30
        chans = pens({"red": (80.0, 0.0), "green": (30.0, 0.0),
                      "magenta": (30.0, 0.0), "blue": (30.0, 0.0),
                      "cyan": (30.0, 0.0)})
        legend = dict(P107_LEGEND, blue=("F Well Casing Pressure", "MPa"))
        self.assertTrue(step1._wells_axes(chans, legend))

    def test_the_surface_pressure_is_not_judged_as_a_well(self):
        chans = pens({"red": (300.0, 0.0), "green": (30.0, 0.0)})
        self.assertTrue(step1._wells_axes(chans, P107_LEGEND))

    def test_a_kpa_well_is_judged_in_kpa(self):
        chans = pens({"green": (30000.0, 0.0)})
        self.assertTrue(step1._wells_axes(
            chans, {"green": ("B Well Casing Pressure", "kPa")}))


def chart(page, labels, borrow=False):
    """A STEP treatment result: {label: (colour, axis top, unit)}."""
    r = {"type": "series", "source": "STEP surface chart (raster)", "page": page,
         "meta": {"stage": str(page)},
         "data": {lb: np.ones(5) for lb in labels},
         "units": {lb: u for lb, (_f, _t, u) in labels.items()},
         "scales": {lb: (t, 0.0) for lb, (_f, t, _u) in labels.items()},
         "frames": {lb: (t, 0.0) for lb, (_f, t, _u) in labels.items()},
         "deduced": {}, "labels": {},
         "pen_fams": {lb: f for lb, (f, _t, _u) in labels.items()}}
    if borrow:
        r["borrow_names"] = True
    return r


class BorrowedNames(unittest.TestCase):
    def test_the_coil_rate_takes_the_name_the_book_gives_it(self):
        # 00247: p105 names the magenta on 0..1.6, p107 cannot; p108 is the
        # offset chart, whose magenta is a well on 0..30
        well = chart(108, {"C Well Casing Pressure": ("magenta", 30.0, "MPa")})
        well["offset_wells"] = {"C Well Casing Pressure": {"group": "casing"}}
        rs = [chart(105, {"Surface Pressure": ("red", 80.0, "MPa"),
                          "Coil Fluid Rate": ("magenta", 1.6, "m3/min")}),
              chart(107, {"Surface Pressure": ("red", 80.0, "MPa"),
                          "Series (magenta)": ("magenta", 1.6, "")}, borrow=True),
              well]
        notes = []
        pipeline._step_borrowed_names(rs, notes)
        self.assertIn("Coil Fluid Rate", rs[1]["data"])
        self.assertNotIn("Series (magenta)", rs[1]["data"])
        self.assertEqual(rs[1]["units"]["Coil Fluid Rate"], "m3/min")
        self.assertEqual(rs[1]["frames"]["Coil Fluid Rate"], (1.6, 0.0))
        self.assertTrue(notes)
        self.assertTrue(all("pen_fams" not in r and "borrow_names" not in r for r in rs))

    def test_a_well_lends_no_name(self):
        well = chart(108, {"C Well Casing Pressure": ("magenta", 1.6, "MPa")})
        well["offset_wells"] = {"C Well Casing Pressure": {"group": "casing"}}
        rs = [chart(107, {"Series (magenta)": ("magenta", 1.6, "")}, borrow=True), well]
        pipeline._step_borrowed_names(rs, [])
        self.assertIn("Series (magenta)", rs[0]["data"])

    def test_another_axis_is_another_pen(self):
        rs = [chart(105, {"Coil Fluid Rate": ("magenta", 1.6, "m3/min")}),
              chart(107, {"Series (magenta)": ("magenta", 16.0, "")}, borrow=True)]
        pipeline._step_borrowed_names(rs, [])
        self.assertIn("Series (magenta)", rs[1]["data"])

    def test_only_a_chart_under_the_wrong_legend_borrows(self):
        rs = [chart(105, {"Coil Fluid Rate": ("magenta", 1.6, "m3/min")}),
              chart(107, {"Series (magenta)": ("magenta", 1.6, "")})]
        pipeline._step_borrowed_names(rs, [])
        self.assertIn("Series (magenta)", rs[1]["data"])


if __name__ == "__main__":
    unittest.main()
