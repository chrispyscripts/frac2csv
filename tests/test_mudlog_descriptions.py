"""mudlog_pdf.read_descriptions / lith_mix: what the wellsite geologist wrote
along a printout's log. Made-up pages and words only."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import fitz
except ImportError:          # pragma: no cover
    fitz = None

import mudlog_pdf as M


class Mix(unittest.TestCase):
    def test_shares(self):
        self.assertEqual(M.lith_mix("972 - 1000m Shale (70%): lt - m gy, sb blky; SS (30%): lt gy, qtzs"), {"shale": 70, "sandstone": 30})
        self.assertEqual(M.lith_mix("850 to 870m SHALE: (95%): light grey; SANDSTONE: (5%): light brown"), {"shale": 95, "sandstone": 5})
        self.assertEqual(M.lith_mix("SH (75%): dk gy; SS: lt brn"), {"shale": 75, "sandstone": 25}, "the one rock left: the rest")

    def test_one_rock_is_all_of_it(self):
        self.assertEqual(M.lith_mix("SS lt-med brn, slt-vf l gr, 6-9% slty/arg mtx"), {"sandstone": 100})
        self.assertEqual(M.main_rock({"sandstone": 100}), "sandstone")

    def test_rocks_with_no_shares(self):
        mix = M.lith_mix("SH med-dk gy; SS lt-med brn; SLTST lt gy")
        self.assertEqual(mix, {"shale": None, "sandstone": None, "siltstone": None})
        self.assertEqual(M.main_rock(mix), "shale", "the first named")

    def test_not_rocks(self):
        self.assertEqual(M.lith_mix("Landing point reached @ 6:15 hrs"), {})
        self.assertEqual(M.lith_mix("SS -27.3m TVD 740.2m MD 886.0m"), {}, "sub-sea")
        self.assertEqual(M.lith_mix("SS +3.75 INC 90.48 AZ 90.44"), {})
        self.assertEqual(M.lith_mix("Viking Sand @ 809.8 m MD"), {}, "a formation, not a rock")
        self.assertEqual(M.lith_mix("tr dk cht, rr glau"), {}, "rocks in passing")


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Descriptions(unittest.TestCase):
    """a page of log, depth along x (0.1 m a point from 1000 m), three
    lines of a ranged description set flush, one line apart, each its own
    text; a description set at its depth; a remark; a survey label"""

    def doc(self):
        d = fitz.open()
        p = d.new_page(width=792, height=612)
        lines = ["1010-1030m SH (70%): lt-med gy, sb blky, mod frm,", "slty ip, mmica, tr pyr; SS (30%): lt gy,", "vf gr, w srt, tr glau."]
        for k, t in enumerate(lines):
            p.insert_text((100, 300 + 10 * k), t, fontsize=8)
        p.insert_text((400, 300), "SLTST lt gy, arg, wkly cons, tr pyr", fontsize=8)
        p.insert_text((500, 450), "Landing point reached @ 06:15 hrs", fontsize=8)
        p.insert_text((600, 450), "MD 1061.2 TVD 702.5", fontsize=8)
        page = M.Page({"page": 1, "from": 1000.0, "to": 1079.2, "depth": {"a": 0.1, "b": 1000.0, "coord": "x"},
                       "across": {"origin": 0.0, "sign": 1.0}})
        return d, [page]

    def test_read(self):
        d, pages = self.doc()
        got = M.read_descriptions(d, pages)
        des = [x for x in got if x["kind"] == "description"]
        self.assertEqual([(x["top"], x["base"], x["at"]) for x in des][0], (1010.0, 1030.0, "range"))
        self.assertTrue(des[0]["text"].startswith("1010-1030m SH (70%)") and des[0]["text"].endswith("tr glau."), des[0]["text"])
        self.assertEqual(des[0]["rocks"], {"shale": 70, "sandstone": 30})
        placed = des[1]
        self.assertEqual((placed["at"], placed["rocks"]), ("position", {"siltstone": 100}))
        self.assertAlmostEqual(placed["top"], 1040.0, delta=0.2)
        notes = [x["text"] for x in got if x["kind"] == "note"]
        self.assertEqual(notes, ["Landing point reached @ 06:15 hrs"], "the survey label is left out")


if __name__ == "__main__":
    unittest.main()
