"""STEP offset charts: the neighbouring wells' pressures, named per file.

00243 p42 (#819) printed eight curves and exported one; 00248 p24 (#823) and
p92 (#826) exported F Well's casing pressure as "Prop Conc" and E Well's as
"Slurry Rate", and spliced them into the stage's own channels.

  python3 -m unittest tests.test_offset_charts
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402
import step1                                             # noqa: E402


def chart(page, wells):
    """A STEP result with one offset curve per (label, group, rgb, votes)."""
    data = {"Surface Pressure": np.zeros(10)}
    offs = {}
    for label, group, rgb, votes in wells:
        data[label] = np.ones(10)
        offs[label] = {"group": group, "rgb": list(rgb), "votes": list(votes)}
    return {"type": "series", "source": "STEP surface chart (raster)", "page": page,
            "meta": {"stage": str(page)}, "data": data,
            "units": {k: "MPa" for k in data}, "scales": {}, "frames": {},
            "deduced": {}, "labels": {}, "offset_wells": offs}


YELLOW, GREEN = (243, 248, 57), (163, 241, 69)


class FileVote(unittest.TestCase):
    def test_a_misread_letter_is_outvoted(self):
        rs = [chart(1, [("A Well Offset Pressure", "offset", YELLOW, ("A", "A")),
                        ("B Well Offset Pressure", "offset", GREEN, ("B", "B"))]),
              chart(2, [("A Well Offset Pressure", "offset", YELLOW, ("A", "")),
                        ("S Well Offset Pressure", "offset", GREEN, ("S", ""))]),
              chart(3, [("A Well Offset Pressure", "offset", YELLOW, ("A", "A")),
                        ("B Well Offset Pressure", "offset", GREEN, ("", "B"))])]
        notes = []
        pipeline._offset_well_names(rs, notes)
        self.assertIn("B Well Offset Pressure", rs[1]["data"])
        self.assertNotIn("S Well Offset Pressure", rs[1]["data"])
        self.assertIn("B Well Offset Pressure", rs[1]["units"])
        self.assertTrue(all("offset_wells" not in r for r in rs))
        self.assertTrue(notes)

    def test_the_line_outweighs_the_glyph_where_they_disagree(self):
        # 00269: G read as S alone, as G in the line, on every page
        rs = [chart(p, [("S Well Offset Pressure", "offset", GREEN, ("S", "G"))])
              for p in (1, 2, 3)]
        pipeline._offset_well_names(rs, [])
        self.assertTrue(all("G Well Offset Pressure" in r["data"] for r in rs))

    def test_a_letter_settled_by_shape_outweighs_the_line(self):
        # 00243: B read "S" in the line, B by its straight left stroke
        rs = [chart(p, [("B Well Offset Pressure", "offset", GREEN, ("B", "S", True))])
              for p in (1, 2, 3)]
        pipeline._offset_well_names(rs, [])
        self.assertTrue(all("B Well Offset Pressure" in r["data"] for r in rs))

    def test_a_well_nobody_read_is_named_by_its_colour(self):
        rs = [chart(1, [("Well #f3f839 Offset Pressure", "offset", YELLOW, ())])]
        pipeline._offset_well_names(rs, [])
        self.assertIn("Well #f3f839 Offset Pressure", rs[0]["data"])

    def test_one_letter_goes_to_one_well(self):
        rs = [chart(1, [("A Well Offset Pressure", "offset", YELLOW, ("A", "A")),
                        ("A Well ABD Pressure", "abd", GREEN, ("A",))])]
        pipeline._offset_well_names(rs, [])
        names = sorted(k for k in rs[0]["data"] if "Well" in k)
        self.assertEqual(len(names), 2)
        self.assertIn("A Well Offset Pressure", names)


class OffsetAxes(unittest.TestCase):
    def test_an_abandoned_wells_axis_of_four_mpa_is_kept(self):
        c = {"key": "series-offset-d-well-abd-pressure", "label": "D Well ABD Pressure",
             "unit": "MPa", "axis_frame": (4.0, 0.0)}
        self.assertIsNone(step1.impossible_axis(c))

    def test_a_treating_pressure_on_four_mpa_is_still_refused(self):
        c = {"key": "series-red", "label": "Surface Pressure", "unit": "MPa",
             "axis_frame": (4.0, 0.0)}
        self.assertIsNotNone(step1.impossible_axis(c))


class ChemicalChart(unittest.TestCase):
    def test_a_chemical_chart_carries_no_surface_pressure(self):
        # 00745 p156: the left axis title did not read, pressure was assumed
        chans = [{"label": "Surface Pressure", "unit": "MPa", "key": "series-red"},
                 {"label": "Slurry Rate", "unit": "m3/min", "key": "series-cyan"}]
        step1._name_chemical("c", chans)
        self.assertEqual([c["label"] for c in chans], ["Combined Clean Rate"])

    def test_the_surface_chart_keeps_it(self):
        chans = [{"label": "Surface Pressure", "unit": "MPa", "key": "series-red"}]
        step1._name_chemical("t", chans)
        self.assertEqual(chans[0]["label"], "Surface Pressure")


class OffsetTitle(unittest.TestCase):
    def test_titles_as_the_ocr_reads_them(self):
        self.assertTrue(step1._offset_title("shell canada limited otfset analysis treatment 37"))
        self.assertTrue(step1._offset_title("treatment 1 5,637.18 m - 5,638.23 m _ oc rirfte"))
        self.assertFalse(step1._offset_title("shell canada limited ireatment analysis treatment 1"))
        self.assertFalse(step1._offset_title("shell canada limited chemical analvsis"))


class WellLetters(unittest.TestCase):
    def test_the_casing_pressure_legend_line(self):
        m = step1._OFFSET_WELL.search("— EE Well Casing Pressure (MPa)")
        self.assertEqual(m.group(1), "E")
        m = step1._OFFSET_WELL.search("— 0 Well Casing Pressure (MPa)")
        self.assertEqual(step1._WELL_LETTER.get(m.group(1), m.group(1)), "O")


class FleetChart(unittest.TestCase):
    """00185 (2017, dual fuel): fleet charts, and offset charts whose well
    legend the offset reader does not parse. The colour tables named a
    fleet's diesel substitution, and a well's casing pressure, Prop Conc."""

    LEGEND = ("Surface Pressure (MPa) Slurry Rate (m?/min Amount of Units Running "
              "Amount of Units Substituting Fleet Fuel Rate L/HR "
              "Fleet Avg Substitution % (%) Fleet Avg Load % (%)")

    def fleet(self, text):
        with mock.patch.object(step1.ar, "ocr_words", return_value=[(w,) for w in text.split()]):
            return step1._other_legend(np.zeros((400, 400, 3), np.uint8), (10, 100, 390, 390))

    def test_a_fleet_legend_is_a_fleet_chart(self):
        self.assertEqual(self.fleet(self.LEGEND), "fleet")

    def test_a_well_legend_the_offset_reader_missed_is_a_wells_chart(self):
        # 00185 p49's offset chart
        self.assertEqual(self.fleet(
            "Surface Pressure (MPa) K Well Casing Pressure (MPa) L Well Casing "
            "Pressure (MPa) N Well Casing Pressure (MPa)"), "wells")

    def test_a_treatment_legend_is_not(self):
        self.assertEqual(self.fleet("Surface Pressure (MPa) Slurry Rate (m3/min) "
                                    "Prop Conc (kg/m3) Btm Prop Conc (kg/m3)"), "")


if __name__ == "__main__":
    unittest.main()
