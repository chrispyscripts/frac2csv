"""The mudlog PDF reader's harder cases, its marking, and the Lab's path for
a printout PDF dropped on its own (mudlog_pdf_app.py).

Every printout here is made in the test (see test_mudlog_pdf.py), never a
client's.

Run: python3 -m unittest tests.test_mudlog_pdf_app
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

try:
    import fitz
except ImportError:          # pragma: no cover
    fitz = None

if fitz:
    import mudlog_key as K
    import mudlog_pdf as M
    import mudlog_pdf_app as A
    import test_mudlog_pdf as T

PPM = 72 / 0.0254 / 240


def one_line(values, lo=0.0, hi=500.0, overshoot=True):
    """a curve drawn the way LogViewer draws it with one line: inside the
    scale the line; past its high end the line stops at the first reading
    past it (drawn past the edge, cut off on the page) and goes on one width
    lower, in from the low end, both drawn where it crosses. -> series of
    shares, one per reading"""
    span = hi - lo
    out, prev = [], None
    for v in values:
        p = (v - lo) / span
        here = []
        if p <= 1:
            here.append(p)
            if prev is not None and prev > 1 and overshoot:
                here.append(p - 1)               # the wrap line, coming back
        else:
            here.append(p - 1)                   # the wrap line
            if prev is not None and prev <= 1 and overshoot:
                here.append(p)                   # the line run past the edge
        out.append(here)
        prev = p
    return out


@unittest.skipUnless(fitz, "needs PyMuPDF")
class OneLine(unittest.TestCase):
    def read(self, series, lo=0.0, hi=500.0):
        return [r and r[0] for r in M.read_one_line(series, lo, hi)]

    def test_a_wrap_read_where_the_line_runs_past_the_edge(self):
        vals = [300, 400, 480, 510, 560, 620, 560, 490, 400]
        got = self.read(one_line(vals))
        for v, g in zip(vals, got):
            self.assertAlmostEqual(g, v, delta=0.5)

    def test_a_one_off_pair_in_a_scribble_is_not_a_wrap(self):
        # the line zig-zags across the track; for one depth an edge-crossing
        # stroke sits a track width from the line, then the line jumps on
        series = [[0.1], [0.11], [0.074, 1.069], [0.52], [0.15], [0.06], [0.06], [0.06]]
        got = self.read(series)
        self.assertTrue(all(g < 500 for g in got if g is not None), got)

    def test_a_jump_up_does_not_go_below_the_scale(self):
        # a real sharp rise from near nothing: in the scale, not below it
        series = [[0.05], [0.05], [0.9], [0.9]]
        got = self.read(series)
        self.assertAlmostEqual(got[-1], 450, delta=1)

    def test_a_pair_by_the_low_edge_is_in_the_scale(self):
        series = [[0.98], [0.96, -0.04], [0.9]]
        got = self.read(series)
        self.assertAlmostEqual(got[1], 480, delta=1)
        self.assertAlmostEqual(got[2], 450, delta=1)


def header_page(rows):
    """a page of header rows: [(y, [(x, text)])]"""
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    for y, items in rows:
        for x, t in items:
            pg.insert_text((x, y), t, fontsize=9)
    return doc, pg


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Header(unittest.TestCase):
    def test_a_value_goes_on_to_its_next_line(self):
        _doc, pg = header_page([
            (100, [(40, "Surface Coordinates:"), (160, "75.65 m North of South Boundary")]),
            (112, [(160, "650.00 m West of East Boundary")]),
            (124, [(40, "Region:"), (160, "Saskatchewan")])])
        h = M.read_header([pg])
        self.assertEqual(h["surface_coordinates"], "75.65 m North of South Boundary\n650.00 m West of East Boundary")
        self.assertEqual(h["region"], "Saskatchewan")

    def test_a_label_over_two_lines(self):
        _doc, pg = header_page([
            (100, [(70, "Bottom Hole"), (160, "294.90 m NORTH of surface")]),
            (112, [(61, "Coordinates:"), (160, "OR 692.6 m NORTH of SOUTH")])])
        h = M.read_header([pg])
        self.assertEqual(h.get("bottom_hole_coordinates"), "294.90 m NORTH of surface\nOR 692.6 m NORTH of SOUTH")

    def test_a_value_apart_from_its_label_and_a_label_with_no_colon(self):
        _doc, pg = header_page([
            (100, [(40, "WELL LICENCE NO,"), (200, "12A345"), (300, "UWI:"), (380, "100/01-02-003-04W5/00")])])
        h = M.read_header([pg])
        self.assertEqual(h.get("licence"), "12A345")
        self.assertEqual(h.get("uwi"), "100/01-02-003-04W5/00")

    def test_the_first_label_holds(self):
        _doc, pg = header_page([(100, [(40, "Licence:"), (120, "10H087")]),
                                (300, [(40, "Licence:"), (120, "10H087")])])
        self.assertEqual(M.read_header([pg])["licence"], "10H087")

    def test_a_colon_inside_a_value(self):
        _doc, pg = header_page([(100, [(40, "Operator:"), (120, "Acme Energy Ltd.: Attn. Geology")]),
                                (112, [(40, "Location:"), (120, "Surface: 01-02-3-4W5")])])
        h = M.read_header([pg])
        self.assertEqual(h["operator"], "Acme Energy Ltd.: Attn. Geology")
        self.assertEqual(h["location"], "Surface: 01-02-3-4W5")

    def test_logged_interval_to_in_a_run_of_its_own(self):
        _doc, pg = header_page([(100, [(40, "Logged Interval (m):"), (150, "865.0"), (260, "To:"), (290, "1169.8")])])
        h = M.read_header([pg])
        self.assertTrue(h["logged_interval_top"].startswith("865.0"))
        self.assertTrue(h["logged_interval_bottom"].startswith("1169.8"))


def boxed_log():
    """one log page under header boxes: a "Comments" box, then the header row
    over the columns (boxed, its lines running down into the log), the log
    below with depth labels every 5 m"""
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.draw_rect(fitz.Rect(30, 40, 560, 140), color=(0, 0, 0), width=1)
    pg.insert_text((260, 60), "Comments", fontsize=11)
    pg.insert_text((40, 80), "Drilling Supervisor: Someone", fontsize=11)
    cols = (60.0, 220.0, 256.0, 560.0)
    y_row, y_log = 200.0, 300.0
    for x in cols:
        pg.draw_line((x, y_row), (x, 792), color=(0, 0, 0), width=1)
    pg.draw_line((cols[0], y_row), (cols[-1], y_row), color=(0, 0, 0), width=1)
    pg.draw_line((cols[0], y_log), (cols[-1], y_log), color=(0, 0, 0), width=1)
    pg.insert_text((110, 220), "Data Curves", fontsize=9)
    pg.insert_text((75, 235), "Gamma (API)", fontsize=7, color=(0, 0, 1))
    pg.insert_text((225, 250), "Depth", fontsize=9)
    pg.insert_text((225, 262), "(mKB)", fontsize=9)
    pg.insert_text((350, 255), "Geological Notes", fontsize=9)
    top = 865.0
    d = top
    while (d - top) * PPM + y_log < 780:
        y = y_log + (d - top) * PPM
        pg.insert_text((228, y + 3), "%d" % d, fontsize=7)
        pg.draw_line((cols[0], y), (cols[1], y), color=(0.6, 0.6, 0.6), width=0.5)
        d += 5
    # a gamma line, captioned at the top of the log
    pg.insert_text((cols[0] + 2, y_log + 8), "0", fontsize=6, color=(0, 0, 1))
    pg.insert_text((120, y_log + 8), "Gamma (API)", fontsize=6, color=(0, 0, 1))
    pg.insert_text((cols[1] - 14, y_log + 8), "150", fontsize=6, color=(0, 0, 1))
    pts = [(cols[0] + 40 + 30 * ((i % 7) / 7), y_log + 2 * i) for i in range(int((792 - y_log) / 2) + 1)]
    for a, b in zip(pts, pts[1:]):
        pg.draw_line(a, b, color=(0, 0, 1), width=1.44)
    # the log runs on down a second page
    d0 = top + (792 - y_log) / PPM
    pg = doc.new_page(width=612, height=792)
    for x in cols:
        pg.draw_line((x, 0), (x, 792), color=(0, 0, 0), width=1)
    d = 5 * int(d0 / 5 + 1)
    while (d - d0) * PPM < 780:
        y = (d - d0) * PPM
        pg.insert_text((228, y + 3), "%d" % d, fontsize=7)
        d += 5
    pts = [(cols[0] + 40 + 30 * ((i % 7) / 7), 2 * i) for i in range(397)]
    for a, b in zip(pts, pts[1:]):
        pg.draw_line(a, b, color=(0, 0, 1), width=1.44)
    return doc.tobytes()


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Columns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = M.read(boxed_log(), parts=("tracks", "header", "curves"))

    def test_titles_from_the_header_row_alone(self):
        titles = [t["title"] for t in self.r["tracks"]]
        self.assertEqual(titles, ["Data Curves", "Depth (mKB)", "Geological Notes"])

    def test_what_each_column_holds(self):
        keys = [t["keys"] for t in self.r["tracks"]]
        self.assertIn("curves", keys[0])
        self.assertIn("depth", keys[1])
        self.assertIn("descriptions", keys[2])

    def test_the_log_starts_below_the_header_row(self):
        self.assertAlmostEqual(self.r["depth"]["top"], 865.0, delta=0.15)

    def test_the_header_row_is_not_header(self):
        self.assertNotIn("Data Curves", " ".join(str(v) for v in self.r["header"].values()))

    def test_header_words_split_where_letters_part(self):
        doc = fitz.open()
        pg = doc.new_page(width=300, height=200)
        pg.insert_text((20, 50), "Lithology", fontsize=9)
        pg.insert_text((68, 50), "Grain", fontsize=9)          # straight after, no space
        P = M.Page({"page": 1, "from": 0.0, "to": 10.0, "depth": {"coord": "y", "a": 0.05, "b": 0.0},
                    "across": {"coord": "x", "origin": 0.0, "sign": 1}})
        words = [w[2] for w in M._header_pieces(pg, P, 0.0, 10.0)]
        self.assertIn("Lithology", words)
        self.assertIn("Grain", words)


def frac_like():
    """two pages of a chart: the same column of axis numbers on each"""
    doc = fitz.open()
    for _ in range(2):
        pg = doc.new_page(width=792, height=612)
        for i, v in enumerate(range(0, 100, 10)):
            pg.insert_text((40, 560 - 50 * i), str(v), fontsize=8)
        pg.insert_text((100, 30), "Tr Press (MPa)", fontsize=8, color=(0, 0, 1))
    return doc.tobytes()


@unittest.skipUnless(fitz, "needs PyMuPDF")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf = T.printout()
        cls.out = A.read(cls.pdf, "test.pdf")

    def test_a_printout_is_told_from_a_chart(self):
        self.assertTrue(A.looks_like_mudlog(self.pdf)[0])
        self.assertFalse(A.looks_like_mudlog(frac_like())[0])
        self.assertFalse(A.looks_like_mudlog(b"not a pdf")[0])

    def test_the_payload_the_lab_draws(self):
        p = self.out["payload"]
        self.assertEqual(p["source"], "pdf")
        self.assertEqual(p["well"], "TEST 1")
        self.assertEqual({c["name"] for c in p["curves"]}, {"ROP", "Gamma"})
        self.assertEqual(len(p["curves"][0]["values"]), p["rows"])
        self.assertTrue(p["rocks"])
        self.assertTrue(any(s["term"] == "pyrite" for s in p["symbols"]))
        g = next(c for c in p["curves"] if c["name"] == "Gamma")
        self.assertTrue(g["wraps"])                  # it runs past 150 at 1070-1080

    def test_the_las(self):
        las = self.out["files"]["test.las"].decode()
        self.assertIn("~ASCII DEPT", las)
        rows = [ln for ln in las.split("~ASCII")[1].splitlines()[1:] if ln.strip()]
        self.assertGreater(len(rows), 1000)
        self.assertEqual(len(rows[0].split()), 3)

    def test_a_chart_reads_as_nothing(self):
        try:
            p = A.read(frac_like(), "chart.pdf")["payload"]
        except ValueError:
            return
        self.assertFalse(p["curves"] or p["rocks"] or p["symbols"])


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Marking(unittest.TestCase):
    def test_a_column_split_by_a_line_of_the_printout(self):
        key = {"printout": {"strip_width_pt": 600}, "tracks": [
            {"title": "Lithology and descriptions", "keys": ["descriptions", "rock"], "x0": 99, "x1": 433,
             "snapped": True}]}
        cand = {"tracks": [{"title": "", "keys": [], "x0": 99, "x1": 257},
                           {"title": "Well Bore Cross Section", "keys": ["rock"], "x0": 257, "x1": 433}]}
        self.assertEqual(K.score_tracks(key, cand)["score"], 1.0)

    def test_untitled_and_unseeable_columns(self):
        key = {"printout": {"strip_width_pt": 612}, "tracks": [
            {"title": "Untitled track", "keys": [], "x0": 152, "x1": 159, "snapped": True},
            {"title": "Untitled track", "keys": [], "x0": 0, "x1": 2, "snapped": True},
            {"title": "Untitled track", "keys": [], "x0": 584.5, "x1": 612, "snapped": True}]}
        cand = {"tracks": [{"title": "Slide / Rotate", "keys": ["directional"], "x0": 152, "x1": 159}]}
        s = K.score_tracks(key, cand)
        self.assertEqual(len(s["tracks"]), 1)
        self.assertEqual(s["score"], 1.0)

    def test_header_label_fields_and_the_uwi(self):
        key = {"header": {"well_id": "100/01-02-003-04W5/00", "well_id_label": "Well Id"}}
        s = K.score_header(key, {"header": {"uwi": "100/01-02-003-04W5/00"}})
        self.assertEqual(s["score"], 1.0)
        self.assertNotIn("well_id_label", s["fields"])

    def test_a_rock_under_the_logs_own_code_is_left_out(self):
        key = {"rocks": [{"top": 0, "base": 10, "rock": "raw:BAKKEN"}, {"top": 10, "base": 20, "rock": "shale"}]}
        cand = {"rocks": [{"top": 0, "base": 20, "rock": "shale"}]}
        self.assertEqual(K.score_rocks(key, cand)["score"], 1.0)

    def test_a_curve_the_printout_does_not_print(self):
        key = T.key()
        key["printout"] = {"log_pages": [{"page": 3}]}
        key["curves"].append(dict(key["curves"][0], name="SCALED MWD GR RT"))
        K.mark_printed(key, T.printout())
        printed = {c["name"]: c["printed"] for c in key["curves"]}
        self.assertEqual(printed, {"ROP": True, "Gamma": True, "SCALED MWD GR RT": False})


if __name__ == "__main__":
    unittest.main()
