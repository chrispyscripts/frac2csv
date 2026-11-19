"""The Geology tool (geology_tool.py): a geologist's report read for its
sample descriptions and formation tops, and the CSVs made from them.

The reports are drawn by the test in the layouts real reports use (tops
then intervals; an interval column beside a text column; the interval on
a line of its own; an interval split over two lines; a tops table). The
wells, formations and descriptions are all invented."""
import base64
import csv
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import geology_tool as gt  # noqa: E402

UWI = "100/03-04-005-06W4/00"


def _pdf(pages):
    """pages: [[(x, y, text), ...], ...] -> PDF bytes, each page with the
    same running header and a page number"""
    import fitz
    doc = fitz.open()
    for n, lines in enumerate(pages, 1):
        p = doc.new_page(width=612, height=792)
        p.insert_text((52, 54), "Example Oil Corp.  Example Hz 1-2-3-4", fontsize=9)
        p.insert_text((52, 66), f"UWI: {UWI}", fontsize=9)
        for x, y, t in lines:
            p.insert_text((x, y), t, fontsize=9)
        p.insert_text((546, 754), str(n), fontsize=9)
    return doc.tobytes()


def _para(x, y, text, width=90, lead=13):
    out = []
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append((x, y, line))
            y += lead
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append((x, y, line))
    return out, y + lead


TITLE_PAGE = [(200, 300, "Geological Report"), (200, 330, "Table of Contents"),
              (72, 360, "Sample Descriptions w/ Formation Tops"), (400, 360, "5")]


class TopsThenIntervals(unittest.TestCase):
    """tops listed under the heading, then "812.5-835m: text" paragraphs"""

    def report(self):
        lines = [(206, 90, "Sample Descriptions w/ Formation Tops"),
                 (205, 120, "Upper Shale: 500.5m MD, 495.0m TVD, 160.0m SS."),
                 (180, 135, "Marker Silt: 560.25m MD, 548.0m TVD, 107.0m SS."),
                 (174, 150, "Target Sand / Target Entry Point: 610.0m MD, 590.0m TVD, 65.0m SS."),
                 (194, 165, "Landing Point: 650.0m MD, 600.0m TVD, 55.0m SS.")]
        y = 200
        for top, base, text in [(540, 560, 'SHALE (90%): dark gray, "waxy" in part; SILTSTONE (10%).'),
                                (560, 600, "SILTSTONE (60%): light gray, sub-"),
                                (600, 650, "SANDSTONE (40%): very fine, fair porosity.")]:
            para, y = _para(68, y, f"{top}-{base}m: {text}")
            lines += para
            if top == 560:
                lines.append((68, y, "angular grains, calcareous."))
                y += 13
            y += 20
        return _pdf([TITLE_PAGE, lines])

    def test_samples_tops_and_formations(self):
        r = gt.read(self.report(), "made-up.pdf")
        self.assertEqual(r["uwi"], UWI)
        self.assertEqual([(s["top"], s["base"]) for s in r["samples"]],
                         [(540, 560), (560, 600), (600, 650)])
        self.assertEqual([t["name"] for t in r["tops"]], ["Upper Shale", "Marker Silt", "Target Sand"])
        self.assertEqual([t["name"] for t in r["markers"]], ["Landing Point"])
        t = r["tops"][1]
        self.assertEqual((t["md"], t["tvd"], t["ss"]), (560.25, 548.0, 107.0))
        f = [s["formation"] for s in r["samples"]]
        self.assertEqual(f, ["Upper Shale", "Upper Shale / Marker Silt", "Marker Silt / Target Sand"])
        # a word broken over two lines comes back whole
        self.assertIn("sub-angular grains", r["samples"][1]["text"])
        self.assertEqual(r["tops_from"], "section")
        self.assertEqual(r["warnings"], [])

    def test_csv(self):
        r = gt.read(self.report(), "made-up.pdf")
        text = r["samples_csv"]
        lines = text.split("\r\n")
        # UWI, depth range and the description: no formation
        self.assertEqual(lines[0], "UWI,Depth Range,Description")
        # the description is always in quotes, a quote inside it doubled
        self.assertTrue(lines[1].startswith(f'{UWI},540.0-560.0,"SHALE (90%)'))
        self.assertIn('""waxy""', lines[1])
        self.assertTrue(all(l.endswith('"') for l in lines[1:] if l))
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1], [UWI, "540.0-560.0", 'SHALE (90%): dark gray, "waxy" in part; SILTSTONE (10%).'])
        self.assertTrue(all(len(r) == 3 for r in rows))
        tops = list(csv.reader(io.StringIO(r["tops_csv"])))
        self.assertEqual(tops[0], ["UWI", "Formation", "MD (m)", "TVD (m)", "SS (m)"])
        self.assertEqual(tops[2], [UWI, "Marker Silt", "560.25", "548.0", "107.0"])
        both = gt.samples_csv([r, r])
        self.assertEqual(both.count("UWI,Depth Range"), 1)


class OtherLayouts(unittest.TestCase):
    def test_interval_column_beside_text_md_first_tops(self):
        lines = [(176, 74, "Sample Descriptions - Build & Leg #1"),
                 (77, 107, "Interval Lithology & Comments"),
                 (83, 130, "652.3 Upper Shale: 598.4 m TVD, +93.1 m MSL"),
                 (77, 176, "675-715"), (136, 176, "SHALE(85%) gray, platy,"),
                 (136, 188, "soft, no shows."),
                 (83, 211, "700.0 Lower Shale: 621.7 m TVD, +71.2 m MSL"),
                 (77, 234, "715-765"), (136, 234, "SHALE(90%) gray, friable,"),
                 (136, 246, "trace pyrite, no shows.")]
        r = gt.read(_pdf([lines]), "b.pdf")
        self.assertEqual([(s["top"], s["base"]) for s in r["samples"]], [(675, 715), (715, 765)])
        self.assertEqual(r["samples"][0]["text"], "SHALE(85%) gray, platy, soft, no shows.")
        self.assertEqual([(t["name"], t["md"], t["tvd"], t["ss"]) for t in r["tops"]],
                         [("Upper Shale", 652.3, 598.4, 93.1), ("Lower Shale", 700.0, 621.7, 71.2)])
        self.assertEqual([s["formation"] for s in r["samples"]],
                         ["Upper Shale / Lower Shale", "Lower Shale"])

    def test_interval_on_its_own_line_and_at_tops(self):
        lines = [(208, 73, "Detailed Sample Descriptions"),
                 (188, 111, "KOP at 412.00 m MD; (411.98 m TVD; +268.40 m SS)"),
                 (176, 142, "Upper Shale at 471.20 m MD; (470.30 m TVD; +210.40 m SS)"),
                 (72, 180, "785 - 795"),
                 (72, 195, "SHALE (70%) medium gray, medium hard;"),
                 (72, 210, "SILTSTONE (30%) light gray, friable."),
                 (186, 240, "Target Sand at 805.60 m MD; (690.25 m TVD; -9.85 m SS)"),
                 (72, 270, "795 - 815"),
                 (72, 285, "NON RESERVOIR"),
                 (72, 300, "SANDSTONE (40%) tan, very fine, tight.")]
        r = gt.read(_pdf([lines]), "c.pdf")
        self.assertEqual([(s["top"], s["base"]) for s in r["samples"]], [(785, 795), (795, 815)])
        self.assertEqual(r["samples"][1]["text"], "NON RESERVOIR SANDSTONE (40%) tan, very fine, tight.")
        self.assertEqual([t["name"] for t in r["tops"]], ["Upper Shale", "Target Sand"])
        self.assertEqual([t["name"] for t in r["markers"]], ["KOP"])
        self.assertEqual(r["tops"][1]["ss"], -9.85)
        self.assertEqual([s["formation"] for s in r["samples"]], ["Upper Shale", "Upper Shale / Target Sand"])

    def test_interval_split_over_two_lines(self):
        lines = [(203, 79, "Sample Descriptions w/ Formation Tops"),
                 (54, 118, "Depth (m) Description"),
                 (222, 155, "Target Sand: 1181.4m MD, 731.2m TVD, 21m SS"),
                 (53, 274, "1181.4- SHALE (75%): gray, massive,"),
                 (53, 289, "1205m silty in part, trace pyrite."),
                 (53, 320, "1205- SANDSTONE (30%): light brown, very fine,"),
                 (53, 335, "1230m to fine grains, fair porosity."),
                 (109, 350, "Trace glauconite.")]
        r = gt.read(_pdf([lines]), "d.pdf")
        self.assertEqual([(s["top"], s["base"]) for s in r["samples"]], [(1181.4, 1205), (1205, 1230)])
        self.assertEqual(r["samples"][1]["text"],
                         "SANDSTONE (30%): light brown, very fine, to fine grains, fair porosity. "
                         "Trace glauconite.")

    def test_tops_from_a_tops_table(self):
        table = [(71, 80, "FORMATION TOPS"),
                 (134, 142, "LICENCE: 999999"), (448, 142, "GL: 688.20"),
                 (226, 204, "Prog"), (286, 204, "Prog"), (364, 204, "Actual"), (407, 204, "Actual"),
                 (443, 204, "Actual"),
                 (222, 214, "(m) MD"), (280, 214, "(m) TVD"), (362, 214, "(m) MD"), (403, 214, "(m) TVD"),
                 (443, 214, "(m) SS")]
        y = 228
        for name, a, b, c, d, e in [("Upper Shale", 502.3, 497.0, 501.8, 496.6, 203.1),
                                    ("Marker Silt", 633.5, 584.2, 630.9, 582.8, 117.0),
                                    ("Landing Point", 700.0, 600.0, 701.0, 601.0, 98.0)]:
            table.append((90, y, name))
            for x, v in zip((222, 281, 362, 404, 442), (a, b, c, d, e)):
                table.append((x, y, f"{v:.1f}"))
            y += 14
        desc = [(206, 90, "Sample Descriptions"),
                (68, 130, "600-620m: SHALE (100%): gray."), (68, 160, "620-650m: SHALE (90%): gray.")]
        r = gt.read(_pdf([table, desc]), "e.pdf")
        self.assertEqual(r["tops_from"], "table")
        self.assertEqual([(t["name"], t["md"], t["tvd"], t["ss"]) for t in r["tops"]],
                         [("Upper Shale", 501.8, 496.6, 203.1), ("Marker Silt", 630.9, 582.8, 117.0)])
        self.assertEqual([s["formation"] for s in r["samples"]], ["Upper Shale", "Upper Shale / Marker Silt"])

    def test_tops_from_a_geological_markers_table(self):
        # the columns' names written out, stacked over two lines
        table = [(71, 80, "GEOLOGICAL MARKERS"), (71, 96, "K.B. ELEVATION: 712.45 m"),
                 (90, 196, "FORMATION"), (210, 190, "MEASURED"), (210, 200, "DEPTH (m)"),
                 (300, 190, "TRUE VERTICAL"), (300, 200, "DEPTH (m)"), (400, 190, "MEAN SEA"),
                 (400, 200, "LEVEL (m)")]
        y = 228
        for name, a, b, c in [("Upper Shale", 501.8, 496.6, 215.9), ("KOP", 520.0, 514.0, 198.5),
                              ("Marker Silt", 630.9, 582.8, 129.7)]:
            table.append((90, y, name))
            for x, v in zip((230, 330, 420), (a, b, c)):
                table.append((x, y, f"{v:.1f}"))
            y += 14
        desc = [(206, 90, "Sample Descriptions"),
                (68, 130, "600-620m: SHALE (100%): gray."), (68, 160, "620-650m: SHALE (90%): gray.")]
        r = gt.read(_pdf([table, desc]), "e.pdf")
        self.assertEqual(r["tops_from"], "table")
        self.assertEqual([(t["name"], t["md"], t["tvd"], t["ss"]) for t in r["tops"]],
                         [("Upper Shale", 501.8, 496.6, 215.9), ("Marker Silt", 630.9, 582.8, 129.7)])

    def test_no_samples(self):
        lines = [(206, 79, "Sample Descriptions w/ Formation Tops"),
                 (205, 111, "Upper Shale: 528.10m MD, 522.6m TVD, 174.3m SS."),
                 (68, 267, "No samples were collected from this well.")]
        r = gt.read(_pdf([lines]), "f.pdf")
        self.assertEqual(r["samples"], [])
        self.assertEqual(r["warnings"], ["No samples were collected from this well."])
        self.assertEqual(len(r["tops"]), 1)
        self.assertEqual(r["samples_csv"], "UWI,Depth Range,Description\r\n")

    def test_section_ends_at_the_next_heading(self):
        desc = [(206, 90, "Sample Descriptions"), (68, 130, "600-620m: SHALE (100%): gray.")]
        survey = [(250, 90, "Surveys"), (60, 130, "620.00 88.50 90.10 601.20 -3.10 150.20 150.10 1.20")]
        r = gt.read(_pdf([desc, survey]), "g.pdf")
        self.assertEqual(len(r["samples"]), 1)
        self.assertEqual(r["samples"][0]["text"], "SHALE (100%): gray.")
        self.assertEqual(r["pages"], [1])

    def test_not_a_pdf(self):
        with self.assertRaises(gt.NotAReport):
            gt.read(b"just text", "notes.txt")
        code, out = gt.api({"data": base64.b64encode(b"just text").decode(), "filename": "n.txt"})
        self.assertEqual(code, 422)


class Pieces(unittest.TestCase):
    def test_parse_top(self):
        t = gt.parse_top("Target Sand / TEP: 1181.4m MD, 731.2m TVD, 21m SS")
        self.assertEqual((t["name"], t["md"], t["tvd"], t["ss"], t["marker"]),
                         ("Target Sand", 1181.4, 731.2, 21.0, False))
        self.assertTrue(gt.parse_top("Bottom Hole: 1612m MD, 684.20m TVD, -22.40m SS.")["marker"])
        self.assertEqual(gt.parse_top("Top Marker Sand at 900.0 m MD")["name"], "Marker Sand")
        self.assertIsNone(gt.parse_top("SHALE (85%): dark gray, 6 to 9% porosity"))
        self.assertIsNone(gt.parse_top("812.5-835m: SANDSTONE (20%): light gray"))
        self.assertIsNone(gt.parse_top("Samples were caught and described every five metres from the "
                                       "surface casing at 150 m MD to TD"))


if __name__ == "__main__":
    unittest.main()
