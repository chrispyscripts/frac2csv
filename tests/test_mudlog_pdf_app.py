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

    def test_a_dip_under_a_scale_that_starts_above_nothing(self):
        # gamma 50 - 150: the line runs just under 50 (drawn wrapped in at
        # the top, with the line itself just past the low edge) and back up
        series = [[0.05], [0.03], [-0.02, 0.98], [-0.03, 0.97], [0.02, 1.02], [0.05, 1.05], [0.3], [0.31]]
        got = [r and r[0] for r in M.read_one_line(series, 50.0, 150.0, under=True)]
        for g, want in zip(got, (55, 53, 48, 47, 52, 55, 80, 81)):
            self.assertAlmostEqual(g, want, delta=0.6)
        # a scale from nothing (gas 0 - 500) is run under by junk readings
        # (a pair one width apart by the low edge, where the line just was)
        got = [r and r[0] for r in M.read_one_line([[0.05], [0.03], [-0.02, 0.98], [0.97], [0.04, 1.04], [0.05]],
                                                   0.0, 500.0)]
        self.assertAlmostEqual(got[2], -10, delta=1)
        self.assertAlmostEqual(got[-1], 25, delta=1)
        # a log scale is not
        got = [r and r[0] for r in M.read_one_line([[0.05], [0.03], [-0.02, 0.98], [0.97]], 0.2, 2000.0)]
        self.assertAlmostEqual(got[2], 0.2 + 0.98 * 1999.8, delta=1)

    def test_the_null_drawn_as_a_reading_is_a_gap(self):
        # gas 0 - 10000: the log's null (-999.25) sits just past the low
        # edge, and the line dips to it (its copy one width on, at the top)
        pn = (M.NULL - 0) / 10000.0
        line = [(100.0, 0.14, 100.4, 0.14), (100.4, 0.14, 100.5, pn), (100.5, pn, 100.6, 0.3),
                (100.4, 1.14, 100.5, pn + 1), (100.5, pn + 1, 100.6, 1.3)]
        self.assertEqual(M._null_dips(line, 100.0, 0.1, 0.0, 10000.0), set(range(2, 9)))   # 0.3 m either side
        self.assertEqual(M._null_dips(line, 100.0, 0.1, 0.0, 150.0), set())     # far off: no dip drawn
        # the copy of the dip, then the line and its copy back up from it
        series = [[0.14]] * 4 + [[0.125, 1.127], [0.915], [0.065, 1.067], [0.3, 1.3], [0.32]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 10000.0, nulls={6})]
        self.assertIsNone(got[6])
        self.assertAlmostEqual(got[8], 3200, delta=1)                        # not wrapped
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 10000.0)]
        self.assertAlmostEqual(got[8], 13200, delta=1)                       # (without: read as a wrap)

    def test_just_under_the_low_edge_of_a_scale_from_nothing(self):
        # gas 0 - 10000 runs down to just under 0 (junk readings): the line
        # goes out of the low edge and comes in at the top with nothing
        # drawn across the track, then back up from the low edge
        series = [[0.047, 1.049], [0.021, 1.023], [-0.004, 0.997]] + [[0.9948]] * 5 + \
                 [[0.0136, 1.0154], [0.0636, 1.0653], [0.1135, 1.1152], [0.2], [0.2]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 10000.0)]
        for g in got[3:8]:
            self.assertLess(abs(g), 200)                                     # about nothing, not 9948
        self.assertAlmostEqual(got[-1], 2000, delta=1)                       # not wrapped
        # a real leap up is drawn across the track
        series = [[0.05], [0.05], [0.5], [0.96], [0.96]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 10000.0)]
        self.assertAlmostEqual(got[-1], 9600, delta=1)

    def test_off_the_top_edge_and_in_at_the_low_one_is_a_wrap(self):
        # nothing drawn across the track between: the line went past the
        # top and goes on in from the low edge, climbing slowly
        series = [[0.9], [0.95], [0.995], [], [0.01], [0.02], [0.03], [0.04]]
        got = self.read(series, 0.0, 150.0)
        self.assertAlmostEqual(got[-1], 156, delta=1)
        # a real drop is drawn across the track
        series = [[0.9], [0.95], [0.995], [0.5], [0.01], [0.02], [0.03], [0.04]]
        got = self.read(series, 0.0, 150.0)
        self.assertAlmostEqual(got[-1], 6, delta=1)

    def test_a_dashed_line_dropping_is_not_a_wrap(self):
        # a dashed line: between readings only its dashes are drawn (moves),
        # down through the middle of the track; the drop is real
        series = [[0.8], [0.8], [], [], [], [0.18], [0.18], [0.3], [0.62], [0.62]]
        moves = [[]] * 2 + [[(0.755, 0.775)], [(0.515, 0.535)], [(0.215, 0.235)]] + [[]] * 5
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 1000.0, moves)]
        self.assertAlmostEqual(got[5], 180, delta=1)
        # with nothing drawn between, the same jump is a wrap
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 1000.0, [[]] * 10)]
        self.assertAlmostEqual(got[5], 1180, delta=1)

    def test_junk_under_a_scale_from_nothing_sits_flat(self):
        # gas 0 - 1000 along the bottom, then a pair by the low edge: junk
        # just under; flat for 2 m it stays junk
        lead = [[0.06], [0.05], [0.04], [0.03]]
        flat = lead + [[-0.005, 0.995]] + [[0.995]] * 20 + [[0.02, 1.02], [0.05]]
        got = [r and r[0] for r in M.read_one_line(flat, 0.0, 1000.0)]
        self.assertTrue(all(g is None or abs(g) <= 20 for g in got[4:-1]), got)
        # a line in from the top that moves for over 1 m is the reading: a
        # wrapped line run out of the bottom, not junk
        moving = lead + [[-0.005, 0.995]] + [[0.99 - 0.01 * j] for j in range(20)]
        got = [r and r[0] for r in M.read_one_line(moving, 0.0, 1000.0)]
        self.assertAlmostEqual(got[-1], 800, delta=2)

    def test_a_dashed_wrapped_line_back_in_at_the_top(self):
        # gas 0 - 2500 wrapped (along the bottom), then the dashed line runs
        # out of the low end and comes in again by the top, falling across
        # the track: the reading is back in the scale
        series = [[0.9], [0.95], [0.03], [0.04], [], [], [], [0.26], [0.27]]
        moves = [[]] * 4 + [[(0.019, 0.039)], [(0.937, 0.965), (0.854, 0.882)], [(0.52, 0.548), (0.353, 0.381)],
                            []] + [[]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 2500.0, moves)]
        self.assertAlmostEqual(got[3], 2600, delta=1)                        # wrapped
        self.assertAlmostEqual(got[-1], 675, delta=1)                        # back in the scale

    def test_another_line_out_of_the_top_is_no_wrap(self):
        # the curve carries on at 0.55 in the middle of its track; another
        # line of its colour runs out of the top beside it
        series = [[0.53], [0.54], [0.549, 0.028, 1.028], [0.559, 0.051, 1.051], [0.568], [0.57]]
        got = self.read(series, 90.0, 0.0)
        self.assertAlmostEqual(got[-1], 90 - 0.57 * 90, delta=0.5)

    def test_back_by_the_top_after_a_gap_is_under_the_scale(self):
        # gamma 50 - 120 at 61, nothing drawn for 3 m, then only the copy in
        # from the top (the reading 44 is under the scale): not 114
        series = [[0.16], [0.164], [0.167]] + [[]] * 31 + [[0.919], [0.919], [0.925], [0.936]]
        got = self.read(series, 50.0, 120.0)
        got = [r and r[0] for r in M.read_one_line(series, 50.0, 120.0, under=True)]
        self.assertAlmostEqual(got[-1], 50 + (0.936 - 1) * 70, delta=0.5)
        # on a scale from nothing the copy is not read under
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 150.0)]
        self.assertAlmostEqual(got[-1], 0.936 * 150, delta=0.5)

    def test_a_sharp_junk_dip_under_a_scale_from_nothing(self):
        # gas 0 - 1000 at 260, a junk reading far under (its bottom cut off
        # the page): down to -0.25, back up from -0.37 within 0.5 m
        line = [(100.0, 0.26, 100.3, 0.26), (100.3, 0.18, 100.4, -0.25), (100.6, -0.37, 100.7, 0.0),
                (100.7, 0.0, 100.8, 0.26)]
        got = M._junk_dives(line, 100.0, 0.1, 0.0, 1000.0)
        self.assertTrue({4, 5, 6} <= got and 0 not in got, got)
        # a wrapped line run out of the low end goes on down: no dip
        line = [(100.0, 0.1, 100.3, 0.05), (100.3, 0.05, 100.4, -0.25)]
        self.assertEqual(M._junk_dives(line, 100.0, 0.1, 0.0, 1000.0), set())
        # read as junk only where the reading was in the scale
        series = [[0.26]] * 4 + [[0.7], [0.35], [0.6], [0.036, 1.033], [0.26], [0.26]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 1000.0, dives={4, 5, 6, 7})]
        self.assertAlmostEqual(got[-1], 260, delta=1)
        series = [[0.9], [0.95], [0.99], [0.03, 1.03], [0.04, 1.04], [0.94, -0.06], [0.8, -0.2], [0.9, -0.1],
                  [0.06, 1.06], [0.1]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 500.0, dives={4, 5, 6, 7, 8})]
        self.assertAlmostEqual(got[-1], 550, delta=1)                       # wrapped before: still read

    def test_a_curve_read_from_under_its_scale(self):
        # gamma 50 - 150 starting at 35 (under): only the copy in from the
        # top is drawn, then up past 50, the main line in from the low end
        series = [[0.85], [0.86], [0.9], [0.95], [0.99, -0.01], [0.04, 1.04], [0.1], [0.3], [0.32]]
        got = [r and r[0] for r in M.read_one_line(series, 50.0, 150.0, under=True, k0=-1)]
        self.assertAlmostEqual(got[0], 35, delta=0.5)
        self.assertAlmostEqual(got[-1], 82, delta=0.5)

    def test_a_mudlogs_own_no_reading_drawn_flat(self):
        # gas 0 - 2000: -99.99 for a stretch is drawn (dashed) just under the
        # low edge, its copy flat at 0.95 inside the track
        pc = 1 + M.JUNK / 2000.0
        line = [(100.0, 0.3, 100.1, -0.05)] + [(100.1 + 0.3 * j, pc, 100.3 + 0.3 * j, pc) for j in range(8)]
        got = M._junk_flats(line, 100.0, 0.1, 0.0, 2000.0)
        self.assertTrue(set(range(2, 22)) <= got, sorted(got))
        self.assertEqual(M._junk_flats(line, 100.0, 0.1, 50.0, 150.0), set())        # not a scale from nothing
        # read as the log holds it, under the scale; the line in again after
        series = [[0.3], [0.2]] + [[pc]] * 20 + [[0.02, 1.02], [0.1], [0.12]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 2000.0, junk=set(range(2, 22)))]
        self.assertEqual(got[5], M.JUNK)
        self.assertAlmostEqual(got[-1], 240, delta=1)

    def test_nothing_drawn_on_both_edges_after_a_low_reading(self):
        # gas 0 - 500 down to nothing (-3): drawn just under the low edge and
        # along the top; then up from nothing: no wrap
        series = [[0.05], [0.02], [-0.006, 0.996], [-0.008, 0.994], [0.006, 1.008], [0.013, 1.015], [0.03], [0.05]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 500.0)]
        self.assertEqual(got[2:4], [0.0, 0.0])
        self.assertAlmostEqual(got[-1], 25, delta=1)
        # from by the top, the same pair is the top (gamma 0 - 150 at 150)
        series = [[0.95], [0.98], [0.008, 0.996], [0.02], [0.05]]
        got = [r and r[0] for r in M.read_one_line(series, 0.0, 150.0)]
        self.assertGreater(got[2], 140)

    def test_after_a_long_gap_the_line_starts_afresh(self):
        # the line high in the track, then nothing for 4 m, then low: no
        # wrap is read across the gap
        series = [[0.8]] * 5 + [[]] * 40 + [[0.15], [0.3], [0.6], [0.62]]
        got = self.read(series)
        self.assertAlmostEqual(got[45], 75, delta=1)
        self.assertAlmostEqual(got[-1], 310, delta=1)

    def test_a_pair_by_the_low_edge_is_in_the_scale(self):
        series = [[0.98], [0.96, -0.04], [0.9]]
        got = self.read(series)
        self.assertAlmostEqual(got[1], 480, delta=1)
        self.assertAlmostEqual(got[2], 450, delta=1)


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Steps(unittest.TestCase):
    def test_a_reading_held_to_its_nearest_recorded_depth(self):
        # read every 0.1 m from 100.0, recorded every 0.5 m: each reading
        # holds from half way to the one before to half way to the next
        vals = [float(i) for i in range(11)]          # 100.0 .. 101.0
        got = M._hold(vals, 100.0, 0.1, 0.5)
        self.assertEqual(got, [0.0, 0.0, 0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 10.0, 10.0, 10.0])

    def test_the_recorded_step_from_corners_in_step(self):
        # a line from reading to reading every 0.5 m (drawn 0.25 m shallow)
        regular = [(100.25 + 0.5 * i, 0.3, 100.75 + 0.5 * i, 0.4) for i in range(60)]
        self.assertEqual(M._recorded_step(regular), 0.5)
        # a line LogViewer drew simplified: corners where it bends, strokes
        # whole numbers of 0.061 m long, some near 0.2 m by chance
        import random
        rnd = random.Random(4)
        d, simplified = 100.0, []
        for _ in range(200):
            L = 0.061 * rnd.choice((2, 3, 3, 4, 5, 6, 7, 8))
            simplified.append((d, 0.3, d + L, 0.4))
            d += L
        self.assertIsNone(M._recorded_step(simplified))

    def test_track_edges_from_the_grid(self):
        lines = [67.0, 170.5, 199.5]
        # a track cut off by the page: no line at its left edge, the grid
        # (every 14.3 pt) puts it a spacing left of the first grid line;
        # the next track's grid close by is no part of it
        grid = [9.5, 24.0, 38.0, 52.5, 77.0, 88.0, 98.0, 108.5]
        a, b = M._grid_edges(grid, lines, 0.0, 67.0)
        self.assertAlmostEqual(a, -4.75, delta=0.3)
        self.assertEqual(b, 67.0)
        # a track with lines at both edges keeps them
        self.assertEqual(M._grid_edges([77.0, 88.0, 98.0, 108.5, 119.0, 129.0, 139.5, 150.0, 160.5],
                                       lines, 67.0, 170.5), (67.0, 170.5))

    def test_held_off_the_end_is_nothing(self):
        got = M._hold([1.0, 2.0, 3.0], 100.2, 0.1, 1.0)
        self.assertEqual(got, [None, None, None])     # 100.2 .. 100.4 hold the reading at 100.0


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
