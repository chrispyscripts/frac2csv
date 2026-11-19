"""geosteer_pdf: curves read off geosteering printouts, their captions in the
three ways these printouts print them. Every page here is made up: a column
of MD labels down the page, a band of curves beside it, captions, lines."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import fitz
except ImportError:          # pragma: no cover
    fitz = None

if fitz:
    import geosteer_pdf as GS

PT_M = 0.0847            # m per pt (1:240)
TOP = 1000.0             # m at the page's top (y = 40)
Y0 = 40.0
X0, X1 = 455.0, 591.8    # the band, across the page
GREEN, RED, BLACK = (0, 0.5, 0), (1, 0, 0), (0, 0, 0)


def y_of(md):
    return Y0 + (md - TOP) / PT_M


def x_of(v, lo, hi, lo_at=X1, hi_at=X0):
    return lo_at + (v - lo) / (hi - lo) * (hi_at - lo_at)


def page(doc, labels=True, top=TOP):
    p = doc.new_page(width=612, height=792)
    if labels:
        md = top
        while y_of(md) < 780:
            p.insert_text((410, y_of(md) + 3), "%g" % md, fontsize=8)
            md += 5.0
    for x in (X0, X1):
        p.draw_line((x, 30), (x, 790), color=BLACK, width=0.5)
    return p


def line(p, pts, colour, width=1.2):
    sh = p.new_shape()
    sh.draw_polyline([fitz.Point(x, y) for x, y in pts])
    sh.finish(color=colour, width=width, closePath=False)
    sh.commit()


def gamma(md):
    return 85.0 + 25.0 * math.sin(md / 3.0)


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Ends(unittest.TestCase):
    """"150 Gamma (API)" at the band's edge, its "50" at the other"""

    def doc(self):
        d = fitz.open()
        p = page(d)
        p.insert_text((X0 + 1, 52), "150 Gamma (API)", fontsize=7, color=GREEN)
        p.insert_text((X1 - fitz.get_text_length("50", fontsize=7), 52), "50", fontsize=7, color=GREEN)
        mds = [TOP + 0.1 * i for i in range(10, 600)]
        line(p, [(x_of(gamma(m), 50, 150), y_of(m)) for m in mds], GREEN)
        return d

    def test_reads_the_line_on_its_scale(self):
        cs = GS.read_curves(self.doc(), TOP, TOP + 62)
        self.assertEqual([(c["name"], c["kind"], c["units"]) for c in cs], [("Gamma", "gamma", "API")])
        c = cs[0]
        self.assertEqual(c["scale"][0][1:], [150.0, 50.0])         # (left end, right end)
        for m in (1005.0, 1020.0, 1047.3):
            v = c["values"][int(round((m - TOP) / 0.1))]
            self.assertAlmostEqual(v, gamma(m), delta=0.5)


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Split(unittest.TestCase):
    """"2500", "Gas (units)", "0": the gas past 2500 drawn again from the
    band's low end (out at the top, in at the bottom, and back)"""

    def doc(self, kind="Gas (units)", hi=2500.0):
        d = fitz.open()
        p = page(d)
        p.insert_text((X0 + 1, 52), "%g" % hi, fontsize=7, color=RED)
        p.insert_text((X0 + 40, 52), kind, fontsize=7, color=RED)
        p.insert_text((X1 - fitz.get_text_length("0", fontsize=7), 52), "0", fontsize=7, color=RED)
        # 1001 m to 1050 m: from 0.6 of the scale up to 1.2 of it and back
        mds = [TOP + 0.1 * i for i in range(10, 500)]
        vals = [hi * (0.6 + 0.6 * math.sin(math.pi * (m - 1001) / 49.0)) for m in mds]
        pts, run = [], []
        for m, v in zip(mds, vals):
            w = v - hi if v > hi else v                 # drawn wrapped past the top
            if run and (w < 0.5 * hi) != (run[-1][2] < 0.5 * hi):
                # the line leaves by one edge and comes in by the other
                last = run[-1]
                out_edge = X0 - 3 if last[2] > 0.5 * hi else X1 + 3
                run.append((out_edge, y_of(m), None))
                pts.append([(x, y) for x, y, _w in run])
                run = [(X1 + 3 if out_edge < X0 else X0 - 3, y_of(m), None)]
            run.append((x_of(w, 0, hi), y_of(m), w))
        pts.append([(x, y) for x, y, _w in run])
        for r in pts:
            line(p, r, RED)
        return d, mds, vals

    def test_unwrapped(self):
        d, mds, vals = self.doc()
        cs = GS.read_curves(d, TOP, TOP + 60)
        self.assertEqual([(c["name"], c["kind"]) for c in cs], [("Gas", "total_gas")])
        got = cs[0]["values"]
        for m, v in zip(mds[::40], vals[::40]):
            self.assertAlmostEqual(got[int(round((m - TOP) / 0.1))], v, delta=25, msg="at %.1f m" % m)
        self.assertGreater(max(x for x in got if x is not None), 2900)     # 1.2 x 2500

    def test_a_gamma_is_not_unwrapped(self):
        # the same drawing captioned as a gamma: a drop from the band's top to
        # its bottom is a reading (gamma out of the casing), not a wrap
        d, mds, vals = self.doc(kind="Gamma (API)", hi=150.0)
        cs = GS.read_curves(d, TOP, TOP + 60)
        self.assertEqual(cs[0]["kind"], "gamma")
        self.assertLessEqual(max(x for x in cs[0]["values"] if x is not None), 150 * 1.05)


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Rows(unittest.TestCase):
    """a black caption, its scale a row of numbers in the curve's colour
    across the band, printed on the log's header page only"""

    def doc(self):
        d = fitz.open()
        h = page(d, labels=False)                      # the header page: no depths
        h.insert_text((X0 + 30, 62), "Drill Rate (min/m)", fontsize=7, color=BLACK)
        for v, x in ((15, X0), (10, X0 + 45.6), (5, X0 + 91.2), (0, X1 - 4)):
            h.insert_text((x if v in (15, 0) else x - 4, 54), "%g" % v, fontsize=7, color=BLACK)
        h.insert_text((X0 + 30, 82), "Gamma Ray (gapi)", fontsize=7, color=BLACK)
        for v, x in ((150, X0), (100, X0 + 45.6), (50, X0 + 91.2), (0, X1 - 4)):
            h.insert_text((x if v in (150, 0) else x - 6, 74), "%g" % v, fontsize=7, color=GREEN)
        p = page(d)
        mds = [TOP + 0.1 * i for i in range(10, 600)]
        line(p, [(x_of(gamma(m), 0, 150, X1, X0), y_of(m)) for m in mds], GREEN)
        line(p, [(x_of(2 + (m % 3), 0, 15, X1, X0), y_of(m)) for m in mds], BLACK)
        return d

    def test_scales_from_the_header_page(self):
        cs = {c["kind"]: c for c in GS.read_curves(self.doc(), TOP, TOP + 62)}
        self.assertEqual(sorted(cs), ["gamma", "rop"])
        g = cs["gamma"]
        self.assertEqual(g["name"], "Gamma Ray")
        self.assertEqual(sorted(g["scale"][0][1:]), [0.0, 150.0])
        for m in (1005.0, 1030.0):
            self.assertAlmostEqual(g["values"][int(round((m - TOP) / 0.1))], gamma(m), delta=1.0)
        self.assertEqual(sorted(cs["rop"]["scale"][0][1:]), [0.0, 15.0])


@unittest.skipUnless(fitz, "needs PyMuPDF")
class RowWords(unittest.TestCase):
    """the row captions' words as some printouts print them"""

    def doc(self, caption="TG (Total Gas) (units)", words=None):
        d = fitz.open()
        h = page(d, labels=False)
        h.insert_text((X0 + 20, 62), caption, fontsize=7, color=BLACK)
        # 0 at the band's low edge (X1), 1500 at its high edge (X0)
        words = words or [("1500", X0), ("1000", None), ("500", None), ("0", X1)]
        width = X1 - X0
        for i, (w, at) in enumerate(words):
            if at is None:
                v = float(w)
                at = X1 - v / 1500.0 * width - fitz.get_text_length(w, fontsize=7) / 2
            elif at == X1:
                at = X1 - fitz.get_text_length(w, fontsize=7)
            h.insert_text((at, 54), w, fontsize=7, color=RED)
        p = page(d)
        mds = [TOP + 0.1 * i for i in range(10, 600)]
        line(p, [(x_of(400 + 300 * math.sin(m / 4.0), 0, 1500, X1, X0), y_of(m)) for m in mds], RED)
        return d

    def gas(self, d):
        cs = [c for c in GS.read_curves(d, TOP, TOP + 62) if c["kind"] == "total_gas"]
        self.assertEqual(len(cs), 1)
        return cs[0]

    def test_a_name_with_brackets_of_its_own(self):
        g = self.gas(self.doc())
        self.assertEqual(g["name"], "TG (Total Gas)")
        self.assertEqual(sorted(g["scale"][0][1:]), [0.0, 1500.0])
        m = 1020.0
        self.assertAlmostEqual(g["values"][int(round((m - TOP) / 0.1))], 400 + 300 * math.sin(m / 4.0), delta=15)

    def test_two_numbers_printed_as_one_word(self):
        # "1200" and "1500" run together at the band's edge: "15001200"
        # where the text runs from the high end
        w = X1 - X0
        words = [("15001200", X0), ("900", None), ("600", None), ("300", None), ("0", X1)]
        g = self.gas(self.doc("Total Gas (units)", words))
        self.assertEqual(sorted(g["scale"][0][1:]), [0.0, 1500.0])


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Frames(unittest.TestCase):
    """a page's depths from its MD labels"""

    def two_pages(self, first):
        d = fitz.open()
        p = first(d)
        p.insert_text((X0 + 1, 52), "150 Gamma (API)", fontsize=7, color=GREEN)
        p.insert_text((X1 - fitz.get_text_length("50", fontsize=7), 52), "50", fontsize=7, color=GREEN)
        mds = [TOP + 0.1 * i for i in range(10, 600)]
        line(p, [(x_of(gamma(m), 50, 150), y_of(m)) for m in mds], GREEN)
        # the next page goes on from 1060 m, its own labels down it
        top2 = TOP + 60.0
        q = d.new_page(width=612, height=792)
        md = top2
        while Y0 + (md - top2) / PT_M < 780:
            q.insert_text((410, Y0 + (md - top2) / PT_M + 3), "%g" % md, fontsize=8)
            md += 5.0
        for x in (X0, X1):
            q.draw_line((x, 30), (x, 790), color=BLACK, width=0.5)
        line(q, [(x_of(gamma(m), 50, 150), Y0 + (m - top2) / PT_M) for m in (top2 + 0.1 * i for i in range(10, 600))], GREEN)
        return d

    def check(self, d, mds):
        cs = GS.read_curves(d, TOP, TOP + 120)
        g = next(c for c in cs if c["kind"] == "gamma")
        for m in mds:
            self.assertAlmostEqual(g["values"][int(round((m - TOP) / 0.1))], gamma(m), delta=1.0, msg="at %.1f m" % m)

    def test_a_cross_sections_labels_in_the_logs_range(self):
        # the first page also prints a TVD scale down it: more labels than
        # its MD's, their values in the log's range, on another scale
        def first(d):
            p = page(d)
            for i in range(16):
                p.insert_text((300, 60 + 45 * i), "%g" % (TOP + 2 + i), fontsize=8)
            return p
        self.check(self.two_pages(first), (1005.0, 1030.0, 1050.0))

    def test_a_page_with_four_labels(self):
        # the log starts low on its first page: four MD labels on it
        def first(d):
            p = d.new_page(width=612, height=792)
            for md in (1040.0, 1045.0, 1050.0, 1055.0):
                p.insert_text((410, y_of(md) + 3), "%g" % md, fontsize=8)
            for x in (X0, X1):
                p.draw_line((x, 30), (x, 790), color=BLACK, width=0.5)
            return p
        self.check(self.two_pages(first), (1042.0, 1052.0))


@unittest.skipUnless(fitz, "needs PyMuPDF")
class HasRows(unittest.TestCase):
    def test_rows_and_ends(self):
        self.assertTrue(GS.has_rows(Rows().doc(), TOP, TOP + 62))
        self.assertFalse(GS.has_rows(Ends().doc(), TOP, TOP + 62))

    def test_the_printout_reader_says_which(self):
        import mudlog_pdf as M
        r = M.read(Rows().doc().tobytes(), parts={"curves"})
        self.assertEqual(sorted(c["kind"] for c in r["curves"]), ["gamma", "rop"])
        self.assertTrue(any("row of numbers" in n for n in r["notes"]))


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Printout(unittest.TestCase):
    def test_mudlog_pdf_reads_them_when_it_finds_no_captions_of_its_own(self):
        import mudlog_pdf as M
        r = M.read(Ends().doc().tobytes(), parts={"curves"})
        self.assertEqual([c["kind"] for c in r["curves"]], ["gamma"])
        self.assertTrue(any("geosteering" in n for n in r["notes"]))
        self.assertFalse(any("no curve captions found" in n for n in r["notes"]))


@unittest.skipUnless(fitz, "needs PyMuPDF")
class Pieces(unittest.TestCase):
    def test_follow_takes_the_long_line(self):
        # at a depth two lines of a colour: the curve's (long) and a short
        # shape; the long one's, then the one nearest the reading before
        cands = {0: [(10.0, 30.0)], 1: [(11.0, 30.0), (90.0, 2.0)], 2: [(12.0, 30.0), (40.0, 25.0)]}
        self.assertEqual(GS._follow(cands, 3), [10.0, 11.0, 12.0])

    def test_a_wrap_needs_the_line_past_the_top(self):
        scale = lambda j: (0.0, 100.0)
        # 95, then 5 with the line past the top between: 105
        self.assertEqual(GS._unwrap([90.0, 95.0, 5.0, 10.0], scale, {2: (True, False)}), [90.0, 95.0, 105.0, 110.0])
        # the same drop with nothing past the top: a reading
        self.assertEqual(GS._unwrap([90.0, 95.0, 5.0, 10.0], scale, {}), [90.0, 95.0, 5.0, 10.0])

    def test_two_gammas_are_two_curves(self):
        self.assertNotEqual(GS._key({"kind": "gamma", "name": "Gamma"}),
                            GS._key({"kind": "gamma", "name": "Gamma Down"}))


if __name__ == "__main__":
    unittest.main()
