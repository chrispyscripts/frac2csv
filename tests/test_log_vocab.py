"""The log vocabulary (log_vocab.txt, log_vocab.py).

The names below are the kinds of names the WellSight drive's logs use; the
well locations in them are made up.

Run: python3 -m unittest tests.test_log_vocab
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import log_vocab as V                                           # noqa: E402


class File(unittest.TestCase):
    def test_every_section_has_entries(self):
        for s in V.SECTIONS:
            self.assertTrue(V.entries(s), s)

    def test_symbol_groups_are_wellsight_symbols_groups(self):
        import wellsight_symbols as W
        self.assertEqual(set(V.SYMBOL_GROUPS), set(W.GROUPS) - W.PASSTHROUGH)
        self.assertTrue({e.key for e in V.entries("category")} <= set(W.GROUPS))

    def test_ranks_read_as_written(self):
        sorting = {e.key: V.rank(e.extra) for e in V.entries("sorting")}
        self.assertEqual(sorting, {"poor": 1, "moderate": 2, "moderately_well": 2.5, "well": 3})
        self.assertIsInstance(sorting["poor"], int)

    def test_no_well_locations_in_the_file(self):
        # the repository is public: names only
        import re
        for s in V.SECTIONS:
            for e in V.entries(s):
                for sp in e.spellings:
                    bare = sp.split(":")[-1]
                    self.assertFalse(re.search(r"\d+-\d+-\d+", bare), (s, sp))

    def _load(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(text)
        try:
            return V.load(f.name), V._index(V.load(f.name), f.name)
        finally:
            os.unlink(f.name)

    def test_a_spelling_given_to_two_keys_is_refused(self):
        with self.assertRaises(V.VocabError) as cm:
            self._load("[curve]\ngamma = GR\nrop = ROP, gr\n")
        self.assertIn(":3:", str(cm.exception))

    def test_continuation_lines_and_quoted_commas(self):
        sections, idx = self._load('[curve track]\ncurves = Data Curves,\n    "TG, C1-C5", Drilling\n')
        self.assertEqual(sections["curve track"][0].spellings, ["Data Curves", "TG, C1-C5", "Drilling"])
        self.assertEqual(idx["curve track"]["TGC1C5"], "curves")

    def test_an_unknown_section_is_refused(self):
        with self.assertRaises(V.VocabError):
            self._load("[curves]\ngamma = GR\n")


class Curves(unittest.TestCase):
    def c(self, raw):
        return V.curve(raw)

    def test_listed_names(self):
        for raw, k in [("Gamma", "gamma"), ("ROP", "rop"), ("DRILL TIME", "rop"), ("TG", "total_gas"),
                       ("Total Gas", "total_gas"), ("METHANE (C1)", "methane"), ("Meth", "methane"),
                       ("Prop", "propane"), ("C2", "ethane"), ("MUD WEIGHT", "mud_weight"), ("WOB", "wob"),
                       ("NPHI", "neutron_porosity"), ("Deep", "deep_resistivity"), ("ILM", "medium_resistivity")]:
            self.assertEqual(self.c(raw)["key"], k, raw)
            self.assertEqual(self.c(raw)["how"], "exact", raw)

    def test_c2_propane_is_propane(self):
        # it reads like propane on the logs that use it: "C2" is the channel
        self.assertEqual(self.c("C2-Propane")["key"], "propane")

    def test_qualifiers_are_kept_not_used_to_find(self):
        c = self.c("MWD GR RT U/T 2")
        self.assertEqual((c["key"], c["how"]), ("gamma", "parts"))
        self.assertEqual(c["qualifiers"], ["mwd", "realtime", "uptrack", "#2"])
        self.assertEqual(self.c("Gamma_Ray_Real_Time")["qualifiers"], ["realtime"])
        self.assertEqual(self.c("MWD GR MEMORY")["qualifiers"], ["mwd", "memory"])
        self.assertEqual(self.c("Gamma Ray TVD")["qualifiers"], ["tvd"])

    def test_company_names_come_off(self):
        for raw, k, src in [("Pason Gas", "total_gas", "pason"), ("PasonGamma", "gamma", "pason"),
                            ("Continental Labs Gas", "total_gas", "continental"),
                            ("Weatherford Gamma", "gamma", "weatherford"), ("GR (WF)", "gamma", "weatherford"),
                            ("Total Gas (PASON)", "total_gas", "pason")]:
            c = self.c(raw)
            self.assertEqual((c["key"], c["source"]), (k, src), raw)

    def test_units_in_the_name(self):
        c = self.c("TOTAL GAS (units)")
        self.assertEqual((c["key"], c["unit_hint"]), ("total_gas", "units"))
        c = self.c("Continental Gas Units")
        self.assertEqual((c["key"], c["unit_hint"]), ("total_gas", "units"))
        self.assertEqual(self.c("ROP (min/meter)")["unit_hint"], "min/m")
        self.assertEqual(self.c("Neutron Porosity (LS) %")["unit_hint"], "%")

    def test_a_well_location_is_taken_out_and_noted(self):
        c = self.c("1A1-1_1A2-2 GR REC")
        self.assertEqual((c["key"], c["location"], c["qualifiers"]), ("gamma", True, ["memory"]))
        c = self.c("Offset Gamma 102(01-01-001-01W3")
        self.assertEqual((c["key"], c["location"]), ("gamma", True))
        self.assertIn("offset", c["qualifiers"])
        self.assertEqual(self.c("9A9-9-9B9-9-9-9W2")["key"], None)    # nothing but a location

    def test_legs_runs_and_sidetracks(self):
        self.assertEqual(self.c("Leg #1 Gas")["qualifiers"], ["leg:1"])
        self.assertEqual(self.c("gamma leg 2")["qualifiers"], ["leg:2"])
        self.assertEqual(self.c("1st Run Gamma")["qualifiers"], ["run:1"])
        self.assertEqual(self.c("ST Gamma")["qualifiers"], ["sidetrack"])
        self.assertIn("lateral:1", self.c("MWD GR RT LATERAL (1)")["qualifiers"])

    def test_porosity_matrix(self):
        c = self.c("DPHI for LIME (DPHI)")
        self.assertEqual((c["key"], c["qualifiers"]), ("density_porosity", ["matrix_limestone"]))
        self.assertEqual(self.c("Density Porosity (SS)")["qualifiers"], ["matrix_sandstone"])

    def test_a_name_in_brackets_is_used_when_the_rest_is_not_known(self):
        c = self.c("SSt. Neut. Por (NPRL)")
        self.assertEqual((c["key"], c["how"]), ("neutron_porosity", "bracket"))

    def test_an_unknown_bracket_is_a_note(self):
        c = self.c("Gamma (faulty)")
        self.assertEqual((c["key"], c["notes"]), ("gamma", ["(faulty)"]))

    def test_nothing_is_guessed(self):
        for raw in ("Sand Line", "Zero", "15%", "MWD MEM (cps)", "Gamma thru casing", "Rig Sat Gas", "New Track"):
            self.assertIsNone(self.c(raw)["key"], raw)

    def test_usual_unit(self):
        self.assertEqual(self.c("Gamma")["unit"], "API")
        self.assertEqual(self.c("ROP")["unit"], "min/m")


class Units(unittest.TestCase):
    def test_spellings(self):
        for raw, k in [("API", "API"), ("GAPI", "API"), ("AAPI", "API"), ("AP!", "API"), ("(API)", "API"),
                       ("Min/m", "min/m"), ("MIN/M", "min/m"), ("units", "units"), ("UNITS", "units"),
                       ("per cent", "%"), ("Percent", "%"), ("Ohm-m", "ohm.m"), ("OhmMeters", "ohm.m"),
                       ("Ohms", "ohm.m"), ("kg/m3", "kg/m3"), ("Kg/m3", "kg/m3"), ("kDaN", "kdaN")]:
            self.assertEqual(V.unit(raw)["key"], k, raw)

    def test_sample_spacing_comes_off(self):
        u = V.unit("AAPI/0.1m")
        self.assertEqual((u["key"], u["spacing"]), ("API", "0.1 m"))
        u = V.unit("min/0.5 m")
        self.assertEqual((u["key"], u["spacing"]), ("min/m", "0.5 m"))
        self.assertEqual(V.unit("CPS/O.2m")["key"], "cps")        # a letter O read for a nought
        self.assertEqual(V.unit("CPS / 0.5  ft")["spacing"], "0.5 ft")

    def test_scale_comes_off(self):
        u = V.unit("Units/10000")
        self.assertEqual((u["key"], u["scale"]), ("units", "10000"))

    def test_unknown(self):
        self.assertIsNone(V.unit("%.20")["key"])
        self.assertIsNone(V.unit("")["key"])

    def test_convert(self):
        self.assertAlmostEqual(V.convert(30, "m/h", "min/m"), 2.0)
        self.assertAlmostEqual(V.convert(2, "min/m", "m/hr"), 30.0)
        self.assertAlmostEqual(V.convert(10, "ft", "m"), 3.048)
        self.assertAlmostEqual(V.convert(3.048, "m", "ft"), 10.0)
        self.assertAlmostEqual(V.convert(2.65, "g/cc", "kg/m3"), 2650.0)
        self.assertAlmostEqual(V.convert(0.25, "v/v", "pu"), 25.0)
        self.assertEqual(V.convert(5, "API", "GAPI"), 5)
        self.assertIsNone(V.convert(100, "units", "%"))         # depends on the detector
        self.assertIsNone(V.convert(0, "m/h", "min/m"))


class TracksAndHeader(unittest.TestCase):
    def test_curve_tracks(self):
        for t in ("Data Curves", "Curve Track 1", "TG, C1-C5", "ROP/GAS/GR", "Neutron-Density"):
            self.assertTrue(V.curve_track(t), t)
        for t in ("Geol. Descrs.", "Oil Shows", "Depth"):
            self.assertFalse(V.curve_track(t), t)

    def test_depth_columns(self):
        self.assertEqual(V.depth_column("DEPT"), "md")
        self.assertEqual(V.depth_column("Measured Depth"), "md")
        self.assertEqual(V.depth_column("TVD_Depth"), "tvd")
        self.assertIsNone(V.depth_column("Eng. Data"))

    def test_header_labels(self):
        self.assertEqual(V.header("License Number:")["key"], "licence")
        self.assertEqual(V.header("WELL LICENCE NO.")["key"], "licence")
        self.assertEqual(V.header("K.B. Elevation (m):"), {"key": "kb_elevation", "unit": "m", "section": None})
        self.assertEqual(V.header("Ground Elevation (m):")["key"], "ground_elevation")
        self.assertEqual(V.header("Treminating Formation")["key"], "terminating_formation")

    def test_a_label_for_one_part_of_the_well(self):
        for label, k, part in [("LATERAL SECTION TOTAL DEPTH", "total_depth", "lateral"),
                               ("BUILD SECTION TERMINATING FORMATION", "terminating_formation", "build"),
                               ("BUILD/DIRECTIONAL SECTION START DATE", "start_date", "build"),
                               ("CTIONAL SECTION DRILLING COMPLETED (HEEL)", "completion_date", "build"),
                               ("DRILLING COMPLETED (TOE)", "completion_date", "toe"),
                               ("LATERAL SECTION VERTICAL SECTION", "vertical_section", "lateral"),
                               ("VERTICAL SECTION PLANE", "vertical_section_plane", None)]:
            h = V.header(label)
            self.assertEqual((h["key"], h["section"]), (k, part), label)
        self.assertEqual(V.header("LATERAL SECTION NONSENSE"), {"key": None, "unit": None, "section": None})

    def test_a_curve_track_named_for_its_well(self):
        self.assertTrue(V.curve_track("Gamma TVD Log - SOME OPERATOR HZ 1A1-1-1A2-1-1-1W3"))
        self.assertTrue(V.curve_track("Data Curves 2"))
        self.assertTrue(V.curve_track("1A1-1 GAMMA"))
        self.assertFalse(V.curve_track("Geology - notes"))

    def test_a_label_read_in_its_box(self):
        self.assertEqual(V.header("Company:", box="OPERATOR")["key"], "operator")
        self.assertEqual(V.header("Company:", box="GEOLOGIST")["key"], "geologist_company")
        self.assertEqual(V.header("Name:", box="GEOLOGIST")["key"], "geologist")
        self.assertEqual(V.header("Ground", box="ELEVATIONS")["key"], "ground_elevation")
        self.assertIsNone(V.header("Company:")["key"])          # which company is not known


if __name__ == "__main__":
    unittest.main()
