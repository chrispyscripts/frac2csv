"""A LogViewer printout stitched into one strip on the log's depth scale.

The printouts are made here, not read from a client file: Letter pages with a
header page, a log that starts low on the legend page, runs on from page to
page, a second depth column printed 9 pt off the gridlines, and round
fifty-metre labels printed 9 pt off as some TVD logs do. A horizontal log is
the same thing turned: depth across a landscape page.

Run: python3 -m unittest tests.test_wellsight_print
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import fitz
except ImportError:          # pragma: no cover
    fitz = None

if fitz:
    import wellsight_print as wp

PPM = 72 / 0.0254 / 240          # points per metre at 1:240


def tracks(pg, landscape, run, curve_color=(1, 0, 0)):
    """LogViewer's tracks across a page: the curve track (dark borders, grey
    grid, a red curve in short strokes), then a lithology track (dark
    borders, no colour). Across = x on a portrait page, y on a landscape one."""
    def line(a, b, c0, c1, color, width=0.7):
        if landscape:
            pg.draw_line((c0, a), (c1, b), color=color, width=width)
        else:
            pg.draw_line((a, c0), (b, c1), color=color, width=width)
    for a in (CURVE[0], CURVE[1], LITH[0], LITH[1]):
        line(a, a, 0, run, (0, 0, 0))
    for k in range(1, 10):
        x = CURVE[0] + k * (CURVE[1] - CURVE[0]) / 10
        line(x, x, 0, run, (0.5, 0.5, 0.5), 0.4)
    import math as _m
    for i in range(0, int(run) - 4, 4):
        x0 = 100 + 40 * _m.sin(i / 23.0)
        x1 = 100 + 40 * _m.sin((i + 4) / 23.0)
        line(x0, x1, i, i + 4, curve_color, 1.0)


CURVE, LITH = (40.0, 190.0), (420.0, 480.0)     # across the page, points


def printout(top, bottom, landscape=False, start_y=560.0, second_column=True,
             round_off=True, with_tracks=False, curve_color=(1, 0, 0)):
    """A fake LogViewer printout, depth down (or across) the pages, and the
    true depth at the start of each of its pages."""
    doc = fitz.open()
    starts = {}
    W, H = (792, 612) if landscape else (612, 792)
    pg = doc.new_page(width=W, height=H)                # header page
    pg.insert_text((72, 100), "WELL NAME  TEST 1-1-1-1W4   KB 704.27   TD 1385")
    run = H if not landscape else W                      # page length along depth
    # first log page: legend above, log from start_along to the page end
    along0 = start_y if not landscape else 300.0
    d_at = top - along0 / PPM                            # depth at this page's 0 edge
    while True:
        pg = doc.new_page(width=W, height=H)
        starts[len(doc)] = d_at                          # 1-based page number
        if with_tracks:
            tracks(pg, landscape, run, curve_color)
        if d_at > bottom:
            break
        d_end = d_at + run / PPM
        first = int(max(top, d_at) // 5 + 1) * 5
        for d in range(first, int(min(bottom, d_end)) + 1, 5):
            c = (d - d_at) * PPM
            if not 4 < c < run - 4:
                continue
            off = 9.0 if (round_off and d % 50 == 0) else 0.0
            if landscape:
                pg.draw_line((c, 20), (c, H - 20), width=0.7)
                pg.insert_text((c + off - 9, 150), str(d), fontsize=8)
            else:
                pg.draw_line((20, c), (W - 20, c), width=0.7)
                # the depth track's label, centred on its gridline
                pg.insert_text((200, c + 3 + off), str(d), fontsize=8)
                if second_column:                       # a second column, 9 pt off
                    pg.insert_text((350, c + 12), str(d), fontsize=8)
        if top > d_at:                                   # legend above the log top
            pg.insert_text((72, 60), "LEGEND  Ss Sh Lmst", fontsize=8)
        d_at = d_end
        if d_at >= bottom:
            break
    return doc.tobytes(), starts


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Stitch(unittest.TestCase):
    def check(self, top, bottom, **kw):
        pdf, starts = printout(top, bottom, **kw)
        data, info = wp.stitch(pdf, top, bottom)
        # each page lands where it truly starts: a page placed by the wrong
        # column, or pulled by the off-line round labels, misses by 0.75 m
        for pl in info["placed"]:
            self.assertAlmostEqual(pl["from"], max(top, starts[pl["page"]]), delta=0.05,
                                   msg=f"page {pl['page']}")
        self.assertEqual(info["gaps"], [])
        self.assertAlmostEqual(info["pt_per_m"], PPM, delta=0.01)
        self.assertAlmostEqual(info["height_pt"], (bottom - top) * PPM, delta=0.5)
        self.assertLess(info["worst_seam_m"], 0.05)
        c = info["check"]
        self.assertGreater(c["labels"], 10)
        self.assertLess(c["median_m"], 0.05)
        self.assertNotIn(1, [p["page"] for p in info["placed"]])   # header left out
        return data, info

    def test_strip_log_runs_on_page_to_page(self):
        self.check(575, 815)

    def test_log_starting_low_on_the_legend_page_is_placed_from_the_next(self):
        _, info = self.check(575, 815, start_y=740.0)
        first = info["placed"][0]
        self.assertEqual(first["from"], 575.0)
        self.assertTrue(first["inferred"])

    def test_one_depth_column_for_the_whole_printout(self):
        # the column on the gridlines, not the one printed 9 pt below them
        _, info = self.check(1230, 1415, second_column=True)
        self.assertLessEqual(info["check"]["median_m"], 0.02)

    def test_round_labels_printed_off_their_line_do_not_move_the_page(self):
        _, info = self.check(1060, 1383, round_off=True)
        self.assertGreaterEqual(info["check"]["within_0.1m"], 0.85)

    def test_horizontal_log_turned_so_depth_runs_down(self):
        data, info = self.check(1330, 1970, landscape=True)
        self.assertEqual(info["depth_axis_on_page"], "across")
        pg = fitz.open(stream=data, filetype="pdf")[0]
        self.assertGreater(pg.rect.height, pg.rect.width)

    def test_not_the_printout_of_this_log(self):
        with self.assertRaises(wp.NoDepthScale):
            wp.stitch(printout(575, 815)[0], 2000, 2400)

    def test_render_a_depth_window(self):
        data, info = self.check(575, 815)
        png = wp.render(data, 600, 650, info["top"], info["pt_per_m"], 10)
        self.assertTrue(png.startswith(b"\x89PNG"))



@unittest.skipUnless(fitz, "needs PyMuPDF")
class CurveTrack(unittest.TestCase):
    """For now the views show one compartment of the printout: the track the
    curves are drawn in."""
    def strip(self, landscape):
        pdf, _ = printout(1300, 1400, landscape=landscape, with_tracks=True)
        return wp.stitch(pdf, 1300, 1400)

    def test_the_curve_track_is_found_on_a_strip_log(self):
        data, info = self.strip(False)
        x0, x1 = info["curves_pt"]
        self.assertAlmostEqual(x1 - x0, CURVE[1] - CURVE[0], delta=1.0)

    def test_and_on_a_horizontal_log_turned_to_run_down(self):
        data, info = self.strip(True)
        x0, x1 = info["curves_pt"]
        self.assertAlmostEqual(x1 - x0, CURVE[1] - CURVE[0], delta=1.0)

    def test_only_that_track_is_drawn_and_cut(self):
        data, info = self.strip(False)
        png = wp.render(data, 1320, 1330, 1300, info["pt_per_m"], 20, None, tuple(info["curves_pt"]))
        pm = fitz.Pixmap(png)
        self.assertAlmostEqual(pm.width, round((CURVE[1] - CURVE[0]) * 20 / info["pt_per_m"]), delta=2)
        red = sum(1 for i in range(0, len(pm.samples), 3)
                  if pm.samples[i] > 200 and pm.samples[i + 1] < 80 and pm.samples[i + 2] < 80)
        self.assertGreater(red, 20)                      # the curve is in it
        cut = fitz.open(stream=wp.cut(data, *info["curves_pt"]), filetype="pdf")[0]
        self.assertAlmostEqual(cut.rect.width, CURVE[1] - CURVE[0], delta=1.0)

    def test_a_black_curve_found_by_its_slant(self):
        # a TVD gamma log draws its one curve in black
        pdf, _ = printout(1300, 1400, with_tracks=True, curve_color=(0, 0, 0))
        data, info = wp.stitch(pdf, 1300, 1400)
        x0, x1 = info["curves_pt"]
        self.assertAlmostEqual(x1 - x0, CURVE[1] - CURVE[0], delta=1.0)

    def test_no_coloured_curve_no_track(self):
        pdf, _ = printout(1300, 1400)                    # gridlines and labels only
        data, info = wp.stitch(pdf, 1300, 1400)
        self.assertIsNone(info["curves_pt"])


if __name__ == "__main__":
    unittest.main()
