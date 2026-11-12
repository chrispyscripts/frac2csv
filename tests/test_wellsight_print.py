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


def printout(top, bottom, landscape=False, start_y=560.0, second_column=True,
             round_off=True):
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


if __name__ == "__main__":
    unittest.main()
