"""The geologist's written descriptions in a WellSight log, read
(wellsight_descriptions.py).

The notes below are made up, in the shorthand the drive's 607,379
descriptions are written in, with the turns of phrase that tripped the
reader on the corpus: a share before the rock, a rock followed by a
semicolon, "Salt and pepper" after a heading, porosity spread over several
commas, "n shows".

Run: python3 -m unittest tests.test_wellsight_descriptions
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wellsight_descriptions as D                             # noqa: E402
import wellsight_symbols as W                                  # noqa: E402


def rocks(s):
    return [(c["rock"], c["pct"]) for c in s["rocks"]]


class Kinds(unittest.TestCase):
    def test_what_each_note_is(self):
        for text, kind in (
                ("1200-1205 LS (90%): wh, micxl, tt intxl por, no show; SH (10%): gy", "sample"),
                ("Lower Shale Top: 1250.4 m MD, 1201.2 m TVD, -598.0 m SS", "top"),
                ("Second Marker | @ 577.70 m TVD / +116.40 m Subsea", "top"),
                ("ICP: 1519m MD, 1406.6m TVD @ 0400 hrs", "event"),
                ("TD reached @ 2360.0m MD", "event"),
                ("DEN 1010 | VIS 32 | WL 14.0 | PH 10.5", "mud"),
                ("TEST OIL HZ 1A1-1-1-1W4 | UWI: 100/01-01-001-01W4/00 | KB: 700.1", "header"),
                ("GRND: 695.2 m", "header"),
                ("Geologist asks us to drop down a meter (1260.6 TVD)", "note")):
            self.assertEqual(D.classify(text, "Geol. Descrs.", None, 500, 3000), kind, text)

    def test_a_top_and_its_depths(self):
        t = D.read_top("Lower Shale Top: 1250.4 m MD, 1201.2 m TVD, -598.0 m SS")
        self.assertEqual((t["name"], t["md"], t["tvd"], t["ss"]), ("Lower Shale Top", 1250.4, 1201.2, -598.0))


class Rocks(unittest.TestCase):
    def test_shares_and_headings(self):
        s = D.read_sample("1400-1405 LS (90%): wh to bf, micxl, rr pyr; SH (10%): m to dk gy, sbfis")
        self.assertEqual((s["top"], s["base"]), (1400.0, 1405.0))
        self.assertEqual(rocks(s), [("limestone", 90.0), ("shale", 10.0)])
        self.assertIn(("mineral", "pyrite"), s["accessories"])

    def test_a_share_before_the_rock_and_a_semicolon_after_it(self):
        self.assertEqual(rocks(D.read_sample("1940-1960m 100% SLTST: tan, w srt")), [("siltstone", 100.0)])
        self.assertEqual(rocks(D.read_sample("1365-1375 LS; lt crm, crpxl, tt, ns")), [("limestone", 100.0)])

    def test_words_after_a_heading_are_not_a_new_rock(self):
        s = D.read_sample("820-840 SHALE 55%: gy, silty. SILTSTONE 10%: lt gy, soft. SANDSTONE 35%: "
                          "Salt and peppered, fine grained, sub rounded")
        self.assertEqual(rocks(s), [("shale", 55.0), ("siltstone", 10.0), ("sandstone", 35.0)])
        ss = s["rocks"][2]
        self.assertIn("fine", ss["grain"])
        self.assertIn(("rounding", "subrounded"), ss["accessories"])

    def test_gray_is_a_colour_not_a_grain_size(self):
        s = D.read_sample("820-840 SHALE 100%: Medium gray to dark gray, blocky")
        self.assertEqual(s["rocks"][0]["grain"], [])
        self.assertIn("medium gray", s["rocks"][0]["colour"])

    def test_modifiers_before_the_rock(self):
        s = D.read_sample("2415 - 2434 ABOVE P1 POROSITY DOLOSTONE: light brown, poor to fair intercrystalline porosity")
        self.assertEqual(rocks(s), [("dolomite", 100.0)])

    def test_sorting_and_rounding_the_best_said(self):
        s = D.read_sample("1700-1710 SS (100%): lt gy, sbang - sbrnd, w srtd, v f gr")
        acc = dict(s["rocks"][0]["accessories"])
        self.assertEqual(acc["sorting"], "well")
        self.assertEqual(acc["rounding"], "subrounded")
        self.assertIn("very fine", s["rocks"][0]["grain"])


class Porosity(unittest.TestCase):
    def test_grade_types_and_per_cent(self):
        p = D.read_sample("1200-1205 SS (100%): lt gy, p - fr intgran por (6-8%), no shows")["porosity"]
        self.assertEqual((p["grade_name"], p["types"], p["pct"]), ("Fair", ["intergranular"], 8.0))

    def test_porosity_said_over_several_commas(self):
        p = D.read_sample("1230-1290 SS lt brn, mnr cons, 9-12% intgran, pp, & micvug por, ev lt brn o stng")["porosity"]
        self.assertEqual(p["pct"], 12.0)
        self.assertEqual(p["grade_name"], "Good")
        self.assertEqual(p["types"], ["intergranular", "pinpoint", "vuggy"])

    def test_tight_and_none(self):
        self.assertEqual(D.read_sample("1300-1305 LS: tan, tt intxl por, ns")["porosity"]["grade_name"], "Tight")
        self.assertEqual(D.read_sample("1300-1305 LS: tan, no vis por, ns")["porosity"]["grade_name"],
                         "No visible porosity")

    def test_spellings(self):
        for text, t in (("Fair intrgr por (7-9%)", "intergranular"), ("tt - p rthy por (1-2%)", "earthy"),
                        ("p-tt inxtln por", "intercrystalline")):
            self.assertIn(t, D.read_sample("1300-1305 LS: tan, " + text)["porosity"]["types"], text)


class Shows(unittest.TestCase):
    def level(self, text):
        return D.read_sample("1300-1305 LS: tan, " + text)["show"]["level"]

    def test_no_show_said_every_way(self):
        for t in ("no shows", "ns", "n/s", "n shows", "no vis shows or cut"):
            self.assertEqual(self.level(t), 0, t)

    def test_grades(self):
        self.assertEqual(self.level("tr dull yel flor"), 1)
        self.assertEqual(self.level("ptchy lt brn o stn, wk yel flor, slw mky cut"), 2)
        self.assertEqual(self.level("even lt brn o stng, bri yel flor, fast strmg cut"), 3)
        self.assertEqual(self.level("ptchy o stn, flor and cut aa, abnt free o"), 4)
        self.assertEqual(self.level("even o stn (60%), bri yel flor (80%)"), 4)

    def test_what_kind_of_show(self):
        sh = D.read_sample("1300-1305 LS: tan, ptchy lt brn o stn (35%), bri yel flor, immed strmg cut")["show"]
        self.assertEqual(sh["stain"]["distribution"], "patchy")
        self.assertTrue(sh["fluorescence"]["bright"])
        self.assertTrue(sh["cut"]["strong"])


class OneLog(unittest.TestCase):
    def setUp(self):
        notes = [
            {"depth": 1000.0, "column": "Geol. Descrs.", "text": "1000-1010 SH (100%): gy, sbfis, ns"},
            {"depth": 1010.0, "column": "Geol. Descrs.", "text": "1010-1020 SS (80%): lt gy, fr intgran por (10%), "
                                                                 "even lt brn o stn, bri yel flor, fast cut; SH (20%): gy"},
            {"depth": 1020.0, "column": "Geol. Descrs.", "text": "1020-1030 SS (70%): aa, g intgran por, ptchy o stn, "
                                                                 "yel flor, slw cut; SH (30%): gy"},
            {"depth": 1030.0, "column": "Geol. Descrs.", "text": "1030 LS: tan, tt, no shows"},
            {"depth": 1040.0, "column": "Geol. Descrs.", "text": "1040-1050 LS: tan, tt, no shows"},
            {"depth": 1005.0, "column": "Geol. Descrs.", "text": "Upper Sand Top: 1010.0 m MD, 990.0 m TVD"},
            {"depth": 1050.0, "column": "Eng. Data", "text": "TD reached @ 1050 m MD"},
        ]
        self.d = D.read(notes, 1000, 1050)
        rock_iv = W.rocks_from([{"top": 1000, "base": 1010, "code": "SHALE"}, {"top": 1010, "base": 1030, "code": "SS"},
                                {"top": 1030, "base": 1050, "code": "LMST"}])
        zones = [{"top": 1012.0, "base": 1026.0}]
        self.a = D.analyse(self.d, rock_iv, [], zones)
        self.zones = zones

    def test_notes_sorted_out(self):
        self.assertEqual(len(self.d["samples"]), 5)
        self.assertEqual([t["name"] for t in self.d["tops"]], ["Upper Sand Top"])
        self.assertEqual([e["what"] for e in self.d["events"]], ["TD"])

    def test_a_sample_with_no_base_runs_to_the_next(self):
        s = [x for x in self.d["samples"] if x["top"] == 1030.0][0]
        self.assertEqual(s["base"], 1040.0)

    def test_rocks_weighted_by_share_and_thickness(self):
        by = {r["rock"]: r["m"] for r in self.a["rocks"]}
        self.assertEqual(by["sandstone"], 15.0)
        self.assertEqual(by["shale"], 15.0)
        self.assertEqual(by["limestone"], 20.0)

    def test_the_main_rock_agrees_with_the_column(self):
        self.assertEqual(self.a["rock_column_agrees"]["pct"], 100.0)

    def test_shows_in_the_text_and_beside_the_symbols(self):
        z = self.a["show_zones"]
        self.assertEqual([(x["top"], x["base"], x["strength"]) for x in z], [(1010.0, 1030.0, "Moderate")])
        self.assertEqual(z[0]["porosity"], "Good")
        self.assertEqual(self.a["symbol_zones_described"], 1)
        self.assertEqual(self.zones[0]["described"], "Moderate")

    def test_tables(self):
        rows = list(D.rows_samples(self.d))
        self.assertEqual(rows[0][0], "top_m")
        self.assertEqual(len(rows), 6)
        self.assertEqual(list(D.rows_tops(self.d))[1][:3], ["Upper Sand Top", 1010.0, 990.0])


if __name__ == "__main__":
    unittest.main()
