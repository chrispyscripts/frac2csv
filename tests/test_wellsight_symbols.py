"""A WellSight log's rock types, accessories and other symbols, in one
vocabulary, and what they add up to (wellsight_symbols.py).

The spellings below are ones the 8,954 logs of the WellSight drive use; the
log in Analysis is made up, so the right answers are known.

Run: python3 -m unittest tests.test_wellsight_symbols
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wellsight_symbols as W                                  # noqa: E402


class Vocabulary(unittest.TestCase):
    def test_one_porosity_type_however_it_is_spelt(self):
        for raw in ("INTER", "INTERGRANULAR", "intergranular", "INTGRANULAR", "intergran./xl", "Granular"):
            self.assertEqual(W.normalise("porosity", raw)[0], "intergranular", raw)
        for raw in ("INTXL", "INTXLN", "INTERXLN", "INTERCRYSTALLINE", "intercrystalline"):
            self.assertEqual(W.normalise("porosity", raw)[0], "intercrystalline", raw)

    def test_categories_named_differently_are_one_group(self):
        for cat, g in (("Oil Show", "show"), ("Oil Shows", "show"), ("Oil/Gas Show", "show"),
                       ("Porosity", "porosity"), ("Porosity Type", "porosity"), ("Accessory Minerals", "mineral"),
                       ("Fossil / Rock Builder", "fossil"), ("Dunham", "texture"), ("Sphericity", "rounding"),
                       ("Events", "event"), ("Event", "event"), ("Reservoir Quality", "quality")):
            self.assertEqual(W.group_of(cat), g, cat)

    def test_scales_keep_their_order(self):
        rank = lambda g, raw: W.normalise(g, raw)[2]                       # noqa: E731
        self.assertLess(rank("show", "QUES"), rank("show", "Weak"))
        self.assertLess(rank("show", "Slow/Weak"), rank("show", "Moderate/Moderate"))
        self.assertLess(rank("show", "MODERATE"), rank("show", "Fast/Strong"))
        self.assertEqual(rank("show", "DEAD"), 0)
        self.assertLess(rank("sorting", "POORLY SORTED"), rank("sorting", "MODERATELY WELL SORTED"))
        self.assertLess(rank("sorting", "MODERATELY WELL SORTED"), rank("sorting", "well"))
        self.assertLess(rank("rounding", "SUB ANGULAR"), rank("rounding", "SUB ROUNDED"))
        self.assertLess(rank("quality", "Very Poor"), rank("quality", "EXCELLENT"))

    def test_a_show_says_what_kind_it_is(self):
        self.assertEqual(W.normalise("show", "Visible Fluorescence")[0], "fluorescence")
        self.assertEqual(W.normalise("show", "milky cut")[0], "cut")
        self.assertEqual(W.normalise("show", "EVEN")[0], "even")
        self.assertEqual(W.SHOW_KIND["even"], "stain")

    def test_rock_codes_and_their_modifiers(self):
        self.assertEqual(W.rock_term("SS"), ("sandstone", []))
        self.assertEqual(W.rock_term("SS ARG"), ("sandstone", ["argillaceous"]))
        self.assertEqual(W.rock_term("SLTST SDY"), ("siltstone", ["sandy"]))
        self.assertEqual(W.rock_term("LMST")[0], "limestone")
        self.assertEqual(W.rock_term("SHGY")[0], "shale")
        self.assertEqual(W.rock_term("Pay Zone Sand")[0], "sandstone")

    def test_a_code_it_does_not_know_keeps_its_own_name(self):
        t, n, r = W.normalise("rock", "Bakken")
        self.assertEqual((t, n, r), ("raw:BAKKEN", "Bakken", None))
        t, n, r = W.normalise("mineral", "Crescent Point")
        self.assertTrue(t.startswith("raw:"))
        self.assertEqual(n, "Crescent Point")

    def test_a_symbol_filed_in_the_wrong_group_is_moved(self):
        s = W.symbols_from([{"category": "Mineral", "depth_m": 10.0, "code": "oil stain"}])
        self.assertEqual((s[0]["group"], s[0]["term"]), ("show", "stain"))

    def test_names_in_their_own_right_pass_through(self):
        self.assertEqual(W.normalise("perm", "Type 1d"), ("is:TYPE1D", "Type 1d", None))
        s = W.symbols_from([{"category": "Photos", "depth_m": 10.0, "code": "blank"}])
        self.assertEqual(s, [])                          # an empty photo marker says nothing


class Columns(unittest.TestCase):
    def test_nothing_runs_left_out_slide_bars_read_as_slides(self):
        cols = [{"column": "Intervals", "category": "Interval",
                 "intervals": [{"top_m": 10, "base_m": 20, "symbols": ["CORE"]},
                               {"top_m": 20, "base_m": 25, "symbols": ["NONE"]}]},
                {"column": "Slide / Rotate", "category": "Lithology",
                 "intervals": [{"top_m": 30, "base_m": 31, "symbols": ["COAL"]}]}]
        out = W.columns_from(cols)
        self.assertEqual([(c["group"], c["term"]) for c in out], [("interval", "core"), ("directional", "slide")])


def log():
    """100 m of shale with a 10 m sandstone at 50-60 m; gamma 100 API in
    the shale, 50 in the sandstone; gas 1 unit, 10 across 52-58 m; even
    stain every 2 m from 51 to 57 m with intergranular porosity, and one
    questionable show alone at 90 m."""
    rocks = W.rocks_from([{"top": 0, "base": 25, "code": "SHALE"}, {"top": 25, "base": 50, "code": "SH"},
                          {"top": 50, "base": 60, "code": "SS"}, {"top": 60, "base": 100, "code": "SHALE"}])
    acc = [{"category": "Oil Show", "depth_m": d, "code": "EVEN"} for d in (51.0, 53.0, 55.0, 57.0)]
    acc += [{"category": "Oil Show", "depth_m": 90.0, "code": "QUES"}]
    acc += [{"category": "Porosity Type", "depth_m": d, "code": "INTER"} for d in (53.0, 55.0)]
    acc += [{"category": "Sorting", "depth_m": 55.0, "code": "WELL"}]
    symbols = W.symbols_from(acc)
    step = 0.5
    n = int(100 / step) + 1
    depth = [i * step for i in range(n)]
    curves = [{"mnemonic": "GR", "name": "Gamma", "values": [50.0 if 50 <= d < 60 else 100.0 for d in depth]},
              {"mnemonic": "GAS", "name": "Pason Gas", "values": [10.0 if 52 <= d <= 58 else 1.0 for d in depth]}]
    return rocks, symbols, curves, step


class Analysis(unittest.TestCase):
    def setUp(self):
        rocks, symbols, curves, step = log()
        self.rocks = rocks
        self.a = W.analyse(0.0, 100.0, rocks, symbols, [], curves, 0.0, step)

    def test_neighbouring_intervals_of_one_rock_are_merged(self):
        self.assertEqual([(r["rock"], r["top"], r["base"]) for r in self.rocks],
                         [("shale", 0, 50), ("sandstone", 50, 60), ("shale", 60, 100)])

    def test_rock_thickness_and_share(self):
        by = {r["rock"]: r for r in self.a["rocks"]}
        self.assertEqual(by["shale"]["m"], 90.0)
        self.assertEqual(by["sandstone"]["pct"], 10.0)

    def test_curve_response_by_rock(self):
        by = {r["rock"]: r for r in self.a["rocks"]}
        self.assertEqual(by["shale"]["curves"]["GR"]["mean"], 100.0)
        self.assertEqual(by["sandstone"]["curves"]["GR"]["mean"], 50.0)

    def test_show_symbols_that_run_on_are_one_zone(self):
        z = self.a["show_zones"]
        self.assertEqual(len(z), 2)
        self.assertEqual((z[0]["top"], z[0]["strength"], z[0]["kinds"]), (51.0, "Moderate", ["stain"]))
        self.assertEqual(z[0]["symbols"], 4)
        self.assertGreater(z[0]["base"], 57.0)
        self.assertEqual(z[0]["rocks"], ["Sandstone"])
        self.assertEqual(z[0]["porosity"], ["Intergranular"])
        self.assertEqual(z[0]["sorting"], "Well")
        self.assertEqual(z[1]["strength"], "Questionable")

    def test_gas_over_background_across_a_zone(self):
        z = self.a["show_zones"][0]
        self.assertEqual(z["gas"]["curve"], "GAS")
        self.assertEqual(self.a["gas_background"], 1.0)
        self.assertGreater(z["gas"]["x_background"], 5)
        self.assertGreater(z["score"], self.a["show_zones"][1]["score"])

    def test_counts_by_group(self):
        g = self.a["groups"]
        self.assertEqual(g["show"]["n"], 5)
        self.assertEqual(g["porosity"]["terms"][0]["name"], "Intergranular")
        self.assertEqual(self.a["unknown_symbols"], 0)

    def test_tables(self):
        rows = list(W.rows_zones(self.a))
        self.assertEqual(rows[0][0], "top_m")
        self.assertEqual(len(rows), 3)
        self.assertIn("Sandstone", W.csv_text(W.rows_zones(self.a)))


if __name__ == "__main__":
    unittest.main()
