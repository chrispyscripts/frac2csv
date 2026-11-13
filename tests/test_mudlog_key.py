"""The mudlog answer key's marking (mudlog_key.score).

The key below is made up in the shape build() writes; each test changes a
copy of it the way a PDF reader might get it wrong and checks the mark.
build() itself runs on real logs: set F2C_WS_SAMPLES to a folder holding a
log and its printout to include it.

Run: python3 -m unittest tests.test_mudlog_key
"""
import copy
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mudlog_key as K                                          # noqa: E402

GAMMA = [40 + 30 * ((i * 7) % 11) / 10.0 for i in range(200)]      # 40..70 API, uneven
ROP = [1.0 + (i % 5) * 0.2 for i in range(100)]

KEY = {
    "schema": K.SCHEMA,
    "depth": {"unit": "m", "axis": "MD", "top": 1000.0, "bottom": 1100.0},
    "header": {"well_name": "Made-up Hz 1-1", "licence": "00A000", "kb_elevation": "600.5 m"},
    "tracks": [{"title": "Curve Track 1", "keys": ["curves"], "x0": 0.0, "x1": 165.5, "snapped": True},
               {"title": "Oil Shows", "keys": ["show"], "x0": 300.0, "x1": 308.0, "snapped": True}],
    "curves": [{"name": "Gamma", "kind": "gamma", "units": "API", "unit": "API", "track": "Curve Track 1",
                "top": 1000.0, "step": 0.5, "values": GAMMA},
               {"name": "ROP", "kind": "rop", "units": "min/m", "unit": "min/m", "track": "Curve Track 1",
                "top": 1000.0, "step": 1.0, "values": ROP}],
    "rocks": [{"top": 1000.0, "base": 1050.0, "rock": "shale", "code": "SHALE"},
              {"top": 1050.0, "base": 1100.0, "rock": "sandstone", "code": "SS"}],
    "symbols": [{"depth": 1010.0 + 3 * i, "group": "show", "term": "weak", "code": "WEAK"} for i in range(10)],
    "intervals": [{"top": 1020.0, "base": 1030.0, "group": "directional", "term": "slide", "code": "SLIDE"}],
    "text": [{"depth": 1012.0, "column": "Geol. Descrs.",
              "text": "SH (90%): gy, firm, sl calc\nSS (10%): lt gy, vf gr, wl srt"},
             {"depth": 1060.0, "column": "Geol. Descrs.", "text": "Viking: 1060.0 m MD, 701.2 m TVD"}],
}


def mark(cand, part=None):
    s = K.score(KEY, cand)
    return s if part is None else s[part]["score"]


class Self(unittest.TestCase):
    def test_the_key_marks_itself_full(self):
        s = mark(copy.deepcopy(KEY))
        for part in ("header", "curves", "rocks", "symbols", "intervals", "text", "tracks"):
            self.assertAlmostEqual(s[part]["score"], 1.0, msg=part)
        self.assertAlmostEqual(s["overall"], 1.0)

    def test_an_empty_reading_marks_nothing(self):
        s = mark({})
        self.assertEqual(s["overall"], 0.0)

    def test_parts_not_tried_are_not_marked(self):
        s = K.score(KEY, {"header": KEY["header"]}, parts=("header",))
        self.assertEqual(set(s), {"header", "overall"})
        self.assertEqual(s["overall"], 1.0)


class Header(unittest.TestCase):
    def test_case_spaces_and_punctuation_aside(self):
        c = {"header": {"well_name": "MADE-UP  HZ 1-1", "licence": "00a000", "kb_elevation": "600.5m"}}
        self.assertAlmostEqual(mark(c, "header"), 1.0)

    def test_wrong_and_missing(self):
        s = mark({"header": {"well_name": "Another well", "licence": "00A000"}})["header"]
        self.assertAlmostEqual(s["score"], 1 / 3)
        self.assertEqual(s["fields"], {"well_name": "different", "licence": "same", "kb_elevation": "missing"})


class Curves(unittest.TestCase):
    def cand(self, **change):
        c = copy.deepcopy(KEY)
        for k, v in change.items():
            c["curves"][0][k] = v
        return c

    def test_half_a_step_shallower_is_allowed(self):
        # LogViewer draws a reading half a step above its depth
        s = mark(self.cand(top=999.75))["curves"]["curves"][0]
        self.assertEqual(s["score"], 1.0)
        self.assertEqual(s["shift_m"], -0.25)

    def test_a_finer_grid_read_off_the_drawing(self):
        # a reader samples the drawn line every 0.1 m: the same curve
        fine = [None if v is None else v for v in K._resample(KEY["curves"][0], 1000.0, 0.1, 1000)]
        s = mark(self.cand(top=1000.0, step=0.1, values=fine))["curves"]["curves"][0]
        self.assertGreater(s["score"], 0.99)

    def test_wrong_scale_costs(self):
        s = mark(self.cand(values=[v * 1.1 for v in GAMMA]))["curves"]["curves"][0]
        self.assertLess(s["score"], 0.5)

    def test_half_missing(self):
        s = mark(self.cand(values=GAMMA[:100] + [None] * 100))["curves"]["curves"][0]
        self.assertAlmostEqual(s["coverage"], 0.5, delta=0.01)
        self.assertAlmostEqual(s["score"], 0.5, delta=0.01)

    def test_found_by_kind_not_name(self):
        s = mark(self.cand(name="MWD GR RT"))["curves"]["curves"][0]
        self.assertEqual(s["score"], 1.0)

    def test_not_found(self):
        c = copy.deepcopy(KEY)
        c["curves"] = c["curves"][1:]
        s = mark(c)["curves"]
        self.assertEqual(s["curves"][0]["why"], "not found")
        self.assertAlmostEqual(s["score"], 0.5)


class RocksSymbolsIntervals(unittest.TestCase):
    def test_rock_by_name_or_code(self):
        c = {"rocks": [{"top": 1000.0, "base": 1050.0, "rock": "Shale"}, {"top": 1050.0, "base": 1100.0, "code": "SS"}]}
        self.assertAlmostEqual(mark(c, "rocks"), 1.0)

    def test_half_the_rock_wrong(self):
        c = {"rocks": [{"top": 1000.0, "base": 1100.0, "rock": "shale"}]}
        self.assertAlmostEqual(mark(c, "rocks"), 0.5, delta=0.01)

    def test_symbols_within_half_a_metre(self):
        c = {"symbols": [dict(s, depth=s["depth"] + 0.4) for s in KEY["symbols"]]}
        self.assertAlmostEqual(mark(c, "symbols"), 1.0)
        c = {"symbols": [dict(s, depth=s["depth"] + 0.7) for s in KEY["symbols"]]}
        self.assertAlmostEqual(mark(c, "symbols"), 0.0)

    def test_symbols_by_code(self):
        c = {"symbols": [{"depth": s["depth"], "group": "show", "code": "Weak"} for s in KEY["symbols"][:5]]}
        s = mark(c)["symbols"]
        self.assertEqual((s["recall"], s["precision"]), (0.5, 1.0))

    def test_extra_symbols_cost_precision(self):
        c = {"symbols": KEY["symbols"] + [{"depth": 1090.0, "group": "show", "term": "strong"}] * 10}
        s = mark(c)["symbols"]
        self.assertEqual((s["recall"], s["precision"]), (1.0, 0.5))

    def test_intervals(self):
        c = {"intervals": [{"top": 1020.0, "base": 1025.0, "group": "directional", "term": "slide"}]}
        self.assertAlmostEqual(mark(c, "intervals"), 0.5, delta=0.02)


class Text(unittest.TestCase):
    def test_notes_split_into_printed_lines(self):
        # the PDF gives a note line by line, each a little lower
        c = {"text": [{"depth": 1012.1, "text": "SH (90%): gy, firm, sl calc"},
                      {"depth": 1012.7, "text": "SS (10%): lt gy, vf gr, wl srt"},
                      {"depth": 1060.2, "text": "Viking: 1060.0 m MD,"}, {"depth": 1060.8, "text": "701.2 m TVD"}]}
        s = mark(c)["text"]
        self.assertAlmostEqual(s["score"], 1.0)
        self.assertAlmostEqual(s["precision"], 1.0)

    def test_text_at_the_wrong_depth(self):
        c = {"text": [dict(t, depth=t["depth"] + 20) for t in KEY["text"]]}
        self.assertLess(mark(c, "text"), 0.2)


class Tracks(unittest.TestCase):
    def test_edges_within_two_points(self):
        c = {"tracks": [dict(t, x0=t["x0"] + 1.5, x1=t["x1"] - 1.5) for t in KEY["tracks"]]}
        self.assertAlmostEqual(mark(c, "tracks"), 1.0)
        c = {"tracks": [dict(t, x1=t["x1"] + 3) for t in KEY["tracks"]]}
        self.assertAlmostEqual(mark(c, "tracks"), 0.0)


SAMPLES = os.environ.get("F2C_WS_SAMPLES")


@unittest.skipUnless(SAMPLES and os.path.isdir(SAMPLES), "set F2C_WS_SAMPLES to a folder of logs and printouts")
class Build(unittest.TestCase):
    def test_a_real_log_and_its_printout(self):
        n = 0
        for log in sorted(glob.glob(os.path.join(SAMPLES, "*.*"))):
            pdf = os.path.splitext(log)[0] + ".pdf"
            if os.path.splitext(log)[1].lower() not in (".sl6", ".slg", ".hl6", ".hlg") or not os.path.exists(pdf):
                continue
            key = K.build(log, pdf)
            self.assertTrue(key["printout"]["ok"], log)
            self.assertTrue(key["curves"] and key["text"], log)
            self.assertTrue(all(t["snapped"] for t in key["tracks"]), log)
            self.assertAlmostEqual(K.score(key, key)["overall"], 1.0)
            n += 1
        self.assertTrue(n)


if __name__ == "__main__":
    unittest.main()
