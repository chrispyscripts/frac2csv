"""The Directional Survey tool (survey_tool.py): minimum curvature, the
UWI, and survey stations read from a report PDF or a plain table.

Every survey here is made up: the PDFs are drawn by the test itself in a
survey report's layout (stacked column names, right-aligned numbers, a
second page with no column names, a plot page of grid labels), and the
wells, companies and numbers are invented."""
import base64
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import survey_tool as st  # noqa: E402


def stations(rows):
    return [{"md": md, "inc": inc, "azi": azi} for md, inc, azi in rows]


class MinimumCurvature(unittest.TestCase):
    def test_vertical(self):
        p = st.min_curvature(stations([(0, 0, 0), (100, 0, 0), (250, 0, 0)]))
        self.assertEqual([round(s["tvd"], 6) for s in p], [0, 100, 250])
        self.assertTrue(all(abs(s["ns"]) < 1e-9 and abs(s["ew"]) < 1e-9 for s in p))
        self.assertTrue(all(s["dls"] == 0 for s in p))

    def test_straight_slant(self):
        # 30 degrees off vertical toward the east, all the way down
        p = st.min_curvature(stations([(0, 30, 90), (200, 30, 90)]))
        self.assertAlmostEqual(p[-1]["tvd"], 200 * math.cos(math.radians(30)), places=6)
        self.assertAlmostEqual(p[-1]["ew"], 200 * math.sin(math.radians(30)), places=6)
        self.assertAlmostEqual(p[-1]["ns"], 0, places=6)

    def test_quarter_circle_build(self):
        # vertical to horizontal along a circle of radius R: down R, out R
        R = 300.0
        L = math.pi / 2 * R
        p = st.min_curvature(stations([(0, 0, 45), (L, 90, 45)]))
        self.assertAlmostEqual(p[-1]["tvd"], R, places=6)
        self.assertAlmostEqual(math.hypot(p[-1]["ns"], p[-1]["ew"]), R, places=6)
        self.assertAlmostEqual(p[-1]["ns"], p[-1]["ew"], places=6)
        self.assertAlmostEqual(p[-1]["dls"], 90 / L * 30, places=6)

    def test_tie_in_and_first_station_below_surface(self):
        p = st.min_curvature(stations([(500, 0, 0), (600, 0, 0)]))
        self.assertAlmostEqual(p[0]["tvd"], 500)        # vertical from the surface
        p = st.min_curvature(stations([(500, 10, 0), (600, 10, 0)]), tie=(480.0, 20.0, -5.0))
        self.assertEqual((p[0]["tvd"], p[0]["ns"], p[0]["ew"]), (480.0, 20.0, -5.0))
        self.assertAlmostEqual(p[1]["tvd"], 480 + 100 * math.cos(math.radians(10)), places=6)

    def test_closure_and_vertical_section(self):
        p = st.min_curvature(stations([(0, 0, 0), (100, 90, 135), (400, 90, 135)]))
        az = st.closure_azimuth(p)
        self.assertAlmostEqual(az, 135, places=4)
        st.add_vertical_section(p, az)
        self.assertAlmostEqual(p[-1]["vs"], math.hypot(p[-1]["ns"], p[-1]["ew"]), places=6)
        self.assertEqual(st.closure_azimuth(st.min_curvature(stations([(0, 0, 0), (9, 0, 0)]))), 0.0)


class Uwi(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(st.find_uwi("Well UWI: 100/07-08-019-12W4/02"), "100/07-08-019-12W4/02")
        self.assertEqual(st.find_uwi("Well UWI 100/7-8-19-12W4"), "100/07-08-019-12W4/00")
        self.assertEqual(st.find_uwi("Design: UWI- 102/03-05-27-11W4 AsDrilled"), "102/03-05-027-11W4/00")
        self.assertEqual(st.find_uwi("00012-100070801912W400_x_DIR_SURVEY.pdf"), "100/07-08-019-12W4/00")
        self.assertIsNone(st.find_uwi("Surface: 07-08-019-12W4M, no UWI here"))

    def test_labelled_first_then_most_often(self):
        text = "offset 100/01-01-001-01W4/00\nWell UWI: 102/09-09-009-09W4/00\n100/01-01-001-01W4/00"
        self.assertEqual(st.find_uwi(text), "102/09-09-009-09W4/00")
        text = "plot: 100/01-01-001-01W4/00 100/02-02-002-02W4/00\npage 1 100/02-02-002-02W4/00\n" \
               "page 2 100/02-02-002-02W4/00"
        self.assertEqual(st.find_uwi(text), "100/02-02-002-02W4/00")


class Tables(unittest.TestCase):
    def test_csv_with_header(self):
        txt = "UWI,MD (m),Inc (deg),Azi (deg),TVD (m)\n" \
              "100/01-02-003-04W5/00,0,0,0,0\n100/01-02-003-04W5/00,100,0,0,100\n" \
              "100/01-02-003-04W5/00,200,10,90,199.49\n"
        s = st.read(txt.encode(), "made-up.csv")
        self.assertEqual(s["uwi"], "100/01-02-003-04W5/00")
        self.assertEqual(len(s["stations"]), 3)
        self.assertEqual(s["source"], "table")
        self.assertLess(s["check"]["tvd_max"], 0.01)

    def test_whitespace_table_without_header_uwi_from_name(self):
        txt = "0 0 0\n150 0 0\n300 20 180\n450 40 180\n"
        s = st.read(txt.encode(), "100010200304W500_survey.txt")
        self.assertEqual(s["uwi"], "100/01-02-003-04W5/00")
        self.assertEqual([p["md"] for p in s["stations"]], [0, 150, 300, 450])
        self.assertLess(s["stations"][-1]["ns"], 0)           # heading south
        self.assertIsNone(s["check"])                         # no TVD to check

    def test_feet(self):
        txt = "MD (ft)\tInc\tAzi\tTVD (ft)\n0\t0\t0\t0\n1000\t0\t0\t1000\n"
        s = st.read(txt.encode(), "x.tsv")
        self.assertAlmostEqual(s["stations"][-1]["md"], 304.8)
        self.assertAlmostEqual(s["stations"][-1]["tvd"], 304.8)
        self.assertTrue(any("feet" in w for w in s["warnings"]))

    def test_csv_out(self):
        s = st.read(b"MD,Inc,Azi\n0,0,0\n100,5,45\n", "100010200304W500.csv")
        lines = s["csv"].strip().split("\r\n")
        self.assertEqual(lines[0], "UWI,MD (m),Inc (deg),Azi (deg),TVD (m),N/S (m),E/W (m),"
                                   "DLS (deg/30 m),VS (m)")
        self.assertEqual(lines[2].split(",")[:4], ["100/01-02-003-04W5/00", "100.00", "5.00", "45.00"])
        both = st.to_csv([s, s])
        self.assertEqual(both.count("UWI,MD"), 1)
        self.assertEqual(len(both.strip().split("\r\n")), 5)

    def test_not_a_survey(self):
        with self.assertRaises(st.NotASurvey):
            st.read(b"name,colour\napple,red\n", "fruit.csv")
        code, out = st.api({"data": base64.b64encode(b"").decode(), "filename": "empty.csv"})
        self.assertEqual(code, 422)
        self.assertIn("error", out)


def _report_pdf(path_rows, uwi="100/06-07-008-09W4/00", plot_page=True, header_on_page2=False):
    """A made-up survey report in the usual layout: a title page, a plot
    page with grid labels, then the station table over two pages, column
    names stacked over three lines, numbers right-aligned."""
    import fitz
    doc = fitz.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((72, 90), "Standard Survey Report", fontsize=14)
    p.insert_text((72, 120), "Example Resources Ltd.", fontsize=10)
    p.insert_text((72, 140), f"Well UWI: {uwi}", fontsize=10)
    if plot_page:
        p = doc.new_page(width=792, height=612)
        for k in range(6):
            y = 100 + k * 60
            for j, x in enumerate((80, 200, 320, 440, 560)):
                p.insert_text((x, y), f"{k * 5 + j}", fontsize=8)
                p.insert_text((x + 12, y), "L.S.", fontsize=6)
        p.insert_text((300, 560), "Vertical Section at 90.00° (100 m/cm)", fontsize=8)
    right = [70, 117, 170, 220, 268, 311, 363, 409, 457]
    heads = [("Measured", "Depth", "(m)"), ("", "Inclination", "(°)"), ("", "Azimuth", "(°)"),
             ("Vertical", "Depth", "(m)"), ("", "Subsea", "(m)"), ("", "+N/-S", "(m)"),
             ("", "+E/-W", "(m)"), ("Vertical", "Section", "(m)"), ("Dogleg", "Rate", "(°/30m)")]
    half = len(path_rows) // 2
    for part, rows in enumerate((path_rows[:half], path_rows[half:])):
        p = doc.new_page(width=612, height=792)
        p.insert_text((260, 40), "Survey Report", fontsize=10)
        y = 200
        if part == 0 or header_on_page2:
            for line, yy in zip(range(3), (164, 174, 184)):
                for r, h in zip(right, heads):
                    t = h[line]
                    if t:
                        w = fitz.get_text_length(t, fontsize=7)
                        p.insert_text((r - w, yy), t, fontsize=7)
        for row in rows:
            for r, v in zip(right, row):
                t = f"{v:.2f}"
                w = fitz.get_text_length(t, fontsize=7)
                p.insert_text((r - w, y), t, fontsize=7)
            y += 10.5
    return doc.tobytes()


def _made_up_path():
    """a build to horizontal toward the east, with the report's own
    numbers worked out by minimum curvature (KB 650 m)"""
    raw = [(0, 0, 0), (150, 0, 0), (300, 0.5, 80)]
    md = 300
    for k in range(1, 19):                      # 5 degrees per station to 90
        md += 30
        raw.append((md, min(90, 0.5 + k * 5), 90))
    for k in range(10):
        md += 60
        raw.append((md, 90, 90))
    path = st.min_curvature(stations(raw))
    az = st.closure_azimuth(path)
    st.add_vertical_section(path, az)
    return [(s["md"], s["inc"], s["azi"], s["tvd"], 650 - s["tvd"], s["ns"], s["ew"], s["vs"],
             s["dls"]) for s in path]


class ReportPdf(unittest.TestCase):
    def test_reads_the_table_and_agrees(self):
        rows = _made_up_path()
        s = st.read(_report_pdf(rows), "made-up-report.pdf")
        self.assertEqual(s["source"], "pdf")
        self.assertEqual(s["uwi"], "100/06-07-008-09W4/00")
        # every station, the plot's grid labels left out, the page with no
        # column names joined on
        self.assertEqual([round(p["md"], 2) for p in s["stations"]], [round(r[0], 2) for r in rows])
        self.assertLess(s["check"]["tvd_max"], 0.01)
        self.assertLess(s["check"]["offset_max"], 0.01)
        self.assertEqual(s["report_vs_azimuth"], 90.0)
        self.assertAlmostEqual(s["closure_azimuth"], 90, places=1)
        last = s["stations"][-1]
        self.assertAlmostEqual(last["tvd"], rows[-1][3], places=1)
        self.assertEqual(s["tie"], "surface")

    def test_header_on_every_page(self):
        rows = _made_up_path()
        s = st.read(_report_pdf(rows, plot_page=False, header_on_page2=True), "r.pdf")
        self.assertEqual(len(s["stations"]), len(rows))
        self.assertEqual(s["warnings"], [])

    def test_uwi_in_file_name_differs(self):
        rows = _made_up_path()
        s = st.read(_report_pdf(rows), "00001-100010100101W400_DIR_SURVEY.pdf")
        self.assertEqual(s["uwi"], "100/06-07-008-09W4/00")
        self.assertTrue(any("file name" in w for w in s["warnings"]))

    def test_no_table(self):
        import fitz
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "A letter about a well, with no survey in it.")
        with self.assertRaises(st.NotASurvey):
            st.read(doc.tobytes(), "letter.pdf")

    def test_scrambled_text(self):
        junk = "".join(chr(1 + (i * 7) % 30) + "AQ;:?" for i in range(400))
        self.assertTrue(st._scrambled(junk))
        self.assertFalse(st._scrambled("Survey Report  Measured Depth  Inclination  Azimuth " * 20))

    def test_api(self):
        rows = _made_up_path()
        code, out = st.api({"data": base64.b64encode(_report_pdf(rows)).decode(),
                            "filename": "r.pdf"})
        self.assertEqual(code, 200)
        self.assertTrue(out["csv"].startswith("UWI,MD (m)"))


if __name__ == "__main__":
    unittest.main()
