"""A mudlog read from its printout alone, with the printout's own legend.

The printouts are made here, not read from a client file: a header page, a
legend page (rock patterns and symbols as small pictures with their labels
under headings), then the log, depth down the pages at 1:240, with a curve
track (two curves, each captioned in its own colour between the scale's
two ends, each drawn twice the way LogViewer draws it: a main line held
inside the track and a thin line one scale width lower that runs on past
the track's edge), a depth column, a lithology column of pattern tiles and
symbols.

Run: python3 -m unittest tests.test_mudlog_pdf
"""
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
    import mudlog_key as K
    import mudlog_pdf as M
    import pdf_legend as L

PPM = 72 / 0.0254 / 240          # points per metre at 1:240
TOP, BOTTOM = 1000.0, 1120.0
CURVE = (30.0, 190.0)            # across the page
DEPTH = (190.0, 215.0)
LITH = (215.0, 259.0)
SYM = (259.0, 275.0)
DESC = (275.0, 560.0)
W, H = 612.0, 792.0


def pattern(kind, w=60, h=8):
    """a small picture: a rock pattern or a symbol"""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    if kind == "ss":                        # yellow with dots
        pix.set_rect(pix.irect, (250, 240, 120))
        for x in range(2, w, 6):
            for y in range(1, h, 3):
                pix.set_pixel(x, y, (0, 0, 0))
    elif kind == "sh":                      # grey lines
        for y in range(1, h, 3):
            pix.set_rect(fitz.IRect(0, y, w, y + 1), (60, 60, 60))
    elif kind == "lmst":                    # blue-green bricks
        pix.set_rect(pix.irect, (80, 200, 200))
        for y in range(0, h, 4):
            pix.set_rect(fitz.IRect(0, y, w, y + 1), (0, 0, 0))
    elif kind == "pyr":                     # a box with a P-ish mark
        pix.set_rect(fitz.IRect(0, 0, w, 1), (0, 0, 0))
        pix.set_rect(fitz.IRect(0, h - 1, w, h), (0, 0, 0))
        pix.set_rect(fitz.IRect(2, 2, 4, h - 2), (0, 0, 0))
    elif kind == "strong":                  # a filled circle-ish block
        pix.set_rect(fitz.IRect(1, 1, w - 1, h - 1), (0, 0, 0))
    return pix


def scaled(pix, k):
    """the same picture stored again at k times its size"""
    out = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, pix.width * k, pix.height * k), False)
    for y in range(out.height):
        for x in range(out.width):
            out.set_pixel(x, y, pix.pixel(x // k, y // k))
    return out


def rock_at(d):
    return "ss" if 1040 <= d < 1060 else "lmst" if 1090 <= d < 1100 else "sh"


def gamma_at(d):
    """0..150 scale; runs past 150 (to 210) from 1070 to 1080"""
    import math
    v = 80 + 40 * math.sin((d - TOP) / 7.0)
    if 1070 <= d <= 1080:
        v = 150 + 60 * math.sin((d - 1070) / 10.0 * math.pi)
    return v


def rop_at(d):
    import math
    return 2.0 + 1.5 * math.sin((d - TOP) / 3.0)


SYMBOLS = [(1012.0, "pyr"), (1047.0, "pyr"), (1081.0, "strong"), (1101.0, "pyr")]


def printout(redraw_pictures=False):
    """-> PDF bytes. redraw_pictures stores the log's pictures again at twice
    their size, as another program might, so only their look matches."""
    doc = fitz.open()
    pg = doc.new_page(width=W, height=H)                     # header
    for i, (lab, val) in enumerate((("Well Name:", "TEST 1"), ("Licence:", "0000"), ("Spud Date:", "2010-04-23"))):
        pg.insert_text((72, 100 + 14 * i), lab, fontsize=9)
        pg.insert_text((160, 100 + 14 * i), val, fontsize=9)

    pics = {k: pattern(k) for k in ("ss", "sh", "lmst")}
    pics.update({k: pattern(k, 8, 8) for k in ("pyr", "strong")})
    pg = doc.new_page(width=W, height=H)                     # legend
    pg.insert_text((260, 40), "ROCK TYPES", fontsize=10)
    for i, (k, lab) in enumerate((("ss", "Ss"), ("sh", "Shale"), ("lmst", "Lmst"))):
        r = fitz.Rect(40 + 150 * i, 60, 40 + 150 * i + 43.2, 65.8)
        pg.insert_image(r, pixmap=pics[k])
        pg.insert_text((r.x1 + 6, r.y1), lab, fontsize=9)
    pg.insert_text((250, 110), "ACCESSORIES", fontsize=10)
    pg.insert_text((40, 130), "MINERAL", fontsize=9)
    r = fitz.Rect(40, 140, 45.8, 145.8)
    pg.insert_image(r, pixmap=pics["pyr"])
    pg.insert_text((r.x1 + 20, r.y1), "Pyr", fontsize=9)
    pg.insert_text((250, 180), "OTHER SYMBOLS", fontsize=10)
    pg.insert_text((190, 200), "OIL SHOWS", fontsize=9)
    r = fitz.Rect(190, 210, 195.8, 215.8)
    pg.insert_image(r, pixmap=pics["strong"])
    pg.insert_text((r.x1 + 20, r.y1), "Strong", fontsize=9)

    body = {k: (scaled(p, 2) if redraw_pictures else p) for k, p in pics.items()}
    per_page = H / PPM
    d0 = TOP
    while d0 < BOTTOM:
        pg = doc.new_page(width=W, height=H)
        d1 = min(BOTTOM, d0 + per_page)

        def y(d):
            return (d - d0) * PPM
        yb = y(d1)
        for x in (CURVE[0], CURVE[1], DEPTH[1], LITH[1], SYM[1], DESC[1]):
            pg.draw_line((x, 0), (x, yb), color=(0, 0, 0), width=1.0)
        for d in range(int(d0) // 5 * 5, int(d1) + 1, 5):
            if d0 <= d <= d1:
                pg.draw_line((CURVE[0], y(d)), (DESC[1], y(d)), color=(0, 0, 0), width=0.5)
                if 4 < y(d) < H - 4:
                    pg.insert_text((DEPTH[0] + 3, y(d) + 3), str(d), fontsize=7)
        # captions at the top of each page, in each curve's colour
        for k, (name, lo, hi, col) in enumerate((("ROP (min/m)", "0", "5", (0, 0, 0)),
                                                 ("Gamma (API)", "0", "150", (0, 0, 1)))):
            yy = 12 + 9 * k
            pg.insert_text((CURVE[0] + 2, yy), lo, fontsize=6, color=col)
            pg.insert_text((90, yy), name, fontsize=6, color=col)
            pg.insert_text((CURVE[1] - 4 - 3.3 * len(hi), yy), hi, fontsize=6, color=col)
        # the curves: a reading every 0.5 m
        span = CURVE[1] - CURVE[0]
        for f, lo, hi, col in ((rop_at, 0.0, 5.0, (0, 0, 0)), (gamma_at, 0.0, 150.0, (0, 0, 1))):
            ds = [d0 + 0.5 * i for i in range(int((d1 - d0) / 0.5) + 1)]

            def xs(v):
                return CURVE[0] + (v - lo) / (hi - lo) * span
            main = [(xs(min(max(f(d), lo), hi)), y(d)) for d in ds]
            for a, b in zip(main, main[1:]):
                pg.draw_line(a, b, color=col, width=1.44)
            thin = [(xs(f(d) - (hi - lo)), y(d)) for d in ds]
            for a, b in zip(thin, thin[1:]):
                pg.draw_line(a, b, color=col, width=0.72)
        # rock tiles 0.5 m high, symbols
        d = d0
        while d < d1 - 1e-6:
            e = min(d + 0.5, d1)
            pg.insert_image(fitz.Rect(LITH[0] + 0.5, y(d), LITH[1] - 0.5, y(e)), pixmap=body[rock_at(d)],
                            keep_proportion=False)
            d = e
        for sd, k in SYMBOLS:
            if d0 <= sd < d1:
                pg.insert_image(fitz.Rect(SYM[0] + 4, y(sd) - 2.9, SYM[0] + 9.8, y(sd) + 2.9), pixmap=body[k])
        pg.insert_text((DESC[0] + 4, y(d0 + 3)), "SH, gy, firm", fontsize=7)
        d0 = d1
    return doc.tobytes()


def key():
    """the answer for the printout"""
    step = 0.5
    n = int((BOTTOM - TOP) / step) + 1
    rocks, cur = [], None
    for i in range(int((BOTTOM - TOP) / 0.5)):
        d = TOP + 0.5 * i
        r = {"ss": "sandstone", "sh": "shale", "lmst": "limestone"}[rock_at(d)]
        if cur and cur["rock"] == r:
            cur["base"] = d + 0.5
        else:
            cur = {"top": d, "base": d + 0.5, "rock": r, "code": r}
            rocks.append(cur)
    term = {"pyr": ("mineral", "pyrite"), "strong": ("show", "strong")}
    return {"schema": K.SCHEMA, "depth": {"top": TOP, "bottom": BOTTOM},
            "header": {"well_name": "TEST 1"},
            "curves": [
                {"name": "ROP", "kind": "rop", "top": TOP, "step": step,
                 "values": [round(rop_at(TOP + i * step), 4) for i in range(n)], "scale": [[TOP, 0.0, 5.0]]},
                {"name": "Gamma", "kind": "gamma", "top": TOP, "step": step,
                 "values": [round(gamma_at(TOP + i * step), 4) for i in range(n)], "scale": [[TOP, 0.0, 150.0]]}],
            "rocks": rocks,
            "symbols": [{"depth": d, "group": term[k][0], "term": term[k][1]} for d, k in SYMBOLS],
            "intervals": [], "text": [], "tracks": []}


@unittest.skipUnless(fitz, "PyMuPDF not installed")
class Legend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = fitz.open(stream=printout(), filetype="pdf")
        cls.sw = L.legend(cls.doc, [1])

    def test_each_picture_named_under_its_heading(self):
        got = {(s.label, s.heading, s.group, s.term) for s in self.sw}
        self.assertEqual(got, {("Ss", "ROCK TYPES", "rock", "sandstone"),
                               ("Shale", "ROCK TYPES", "rock", "shale"),
                               ("Lmst", "ROCK TYPES", "rock", "limestone"),
                               ("Pyr", "MINERAL", "mineral", "pyrite"),
                               ("Strong", "OIL SHOWS", "show", "strong")})

    def test_a_box_title_that_is_no_group_names_nothing(self):
        # "ACCESSORIES" starts a box; only "MINERAL" under it gives a group
        self.assertTrue(all(s.group for s in self.sw))

    def test_a_label_must_be_a_label(self):
        self.assertTrue(L._label_like("Sltst"))
        self.assertTrue(L._label_like("Oil Stain"))
        self.assertFalse(L._label_like("600 - 650SH, med gy - dk gy - occ blk, blky"))

    def test_look_alike(self):
        doc = fitz.open(stream=printout(redraw_pictures=True), filetype="pdf")
        sw = L.legend(doc, [1])
        exact = L.Library(sw, doc, look_alike=False)
        alike = L.Library(sw, doc)
        found_exact = found_alike = 0
        for im in doc[3].get_image_info(hashes=True, xrefs=True):
            found_exact += exact.find(im["digest"], im["xref"]) is not None
            s = alike.find(im["digest"], im["xref"], (im["width"], im["height"]))
            found_alike += s is not None
        self.assertEqual(found_exact, 0)
        self.assertGreater(found_alike, 100)
        # symbols only by the exact picture: a letter in a box looks like the next
        sym = [im for im in doc[3].get_image_info(hashes=True, xrefs=True) if im["width"] == 16]
        self.assertTrue(sym)
        self.assertTrue(all(alike.find(im["digest"], im["xref"], (im["width"], im["height"])) is None
                            for im in sym))

    def test_captions(self):
        pg = self.doc[3]
        caps = L.captions(pg, 3, lambda x, y: x)
        got = {(c.name, c.unit, c.kind, c.left, c.right, c.colour) for c in caps}
        self.assertEqual(got, {("ROP", "min/m", "rop", 0.0, 5.0, 0x000000),
                               ("Gamma", "API", "gamma", 0.0, 150.0, 0x0000ff)})

    def test_caption_sideways(self):
        # a page turned: the scale runs up the page, so across = -y
        doc = fitz.open()
        pg = doc.new_page(width=792, height=612)
        pg.insert_text((400, 100), "10", fontsize=6, color=(1, 0, 0))
        pg.insert_text((400, 112), "Gas (units)", fontsize=6, color=(1, 0, 0))
        pg.insert_text((400, 124), "0", fontsize=6, color=(1, 0, 0))
        caps = L.captions(pg, 0, lambda x, y: -y)
        self.assertEqual([(c.name, c.left, c.right) for c in caps], [("Gas", 0.0, 10.0)])

    def test_a_log_scale_with_every_decade_printed(self):
        # sideways: 1 10 Shallow 100 1000 up the page; a black Gamma 0 .. 150
        # beside it is no part of the series
        doc = fitz.open()
        pg = doc.new_page(width=792, height=612)
        red = (1, 0, 0)
        for y, t in ((206, "1"), (184, "10"), (168, "Shallow (ohm.m)"), (152, "100"), (130, "1000")):
            pg.insert_text((400, y), t, fontsize=6, color=red)
        for y, t in ((206, "0"), (168, "Gamma (API)"), (130, "150")):
            pg.insert_text((440, y), t, fontsize=6)
        caps = L.captions(pg, 0, lambda x, y: -y)
        got = {(c.name, c.left, c.right) for c in caps}
        self.assertEqual(got, {("Shallow", 1.0, 1000.0), ("Gamma", 0.0, 150.0)})
        doc.close()

    def test_a_number_run_into_the_next_caption(self):
        # sideways: "30 WOB 0" in blue and "25000 SPP 0" in red, the blue 0
        # and the red caption one text line ("0 SPP (kPa)")
        doc = fitz.open()
        pg = doc.new_page(width=792, height=612)
        blue, red = (0, 0, 1), (1, 0, 0)
        pg.insert_text((400, 130), "30", fontsize=6, color=blue)
        pg.insert_text((400, 146), "WOB (kDaN)", fontsize=6, color=blue)
        pg.insert_text((440, 130), "25000", fontsize=6, color=red)
        tw = fitz.TextWriter(pg.rect)
        font = fitz.Font("helv")
        tw.append((400, 162), "0 ", font=font, fontsize=6)
        tw.write_text(pg, color=blue)
        tw = fitz.TextWriter(pg.rect)
        tw.append((406.5, 162), "SPP (kPa)", font=font, fontsize=6)
        tw.write_text(pg, color=red)
        pg.insert_text((440, 178), "0", fontsize=6, color=red)
        got = {(c.name, c.unit, c.left, c.right) for c in L.captions(pg, 0, lambda x, y: -y)}
        self.assertIn(("WOB", "kDaN", 0.0, 30.0), got)
        doc.close()

    def test_a_stack_of_one_colour_takes_its_numbers_in_order(self):
        # sideways, a stack: 5 10 above, ROP and MUD WT, 0 0 below, all
        # black; the nearest number to ROP is MUD WT's 10
        doc = fitz.open()
        pg = doc.new_page(width=792, height=612)
        for y, t in ((66, "5"), (90, "10"), (103, "ROP (min/m)"), (127, "MUD WT (kg/m3)"), (141, "0"), (164, "0")):
            pg.insert_text((400, y), t, fontsize=6)
        got = {(c.name, c.left, c.right) for c in L.captions(pg, 0, lambda x, y: -y)}
        self.assertEqual(got, {("ROP", 0.0, 5.0), ("MUD WT", 0.0, 10.0)})
        doc.close()

    def test_a_decade_printed_as_a_power(self):
        # sideways: 10 100 Total Gas 1000 1e4 up the page
        doc = fitz.open()
        pg = doc.new_page(width=792, height=612)
        for y, t in ((243, "10"), (214, "100"), (200, "Total Gas (units)"), (179, "1000"), (150, "1e4")):
            pg.insert_text((400, y), t, fontsize=6.5, color=(1, 0, 0))
        got = [(c.name, c.left, c.right) for c in L.captions(pg, 0, lambda x, y: -y)]
        self.assertEqual(got, [("Total Gas", 10.0, 10000.0)])
        doc.close()

    def test_a_description_or_depth_note_is_no_caption(self):
        self.assertIsNone(L._caption_name("m TVD, (-949.33 m SS)"))
        self.assertIsNone(L._caption_name("loose sub rounded quartz and random chert grains. Poor (10%)"))
        self.assertEqual(L._caption_name("Sidetrack 1 MWD GR (API)"), ("Sidetrack 1 MWD GR", "API", "gamma"))
        self.assertIsNone(L._caption_name("z grains and abundant (5%)"))
        self.assertIsNone(L._caption_name("RPM-0"))
        self.assertIsNone(L._caption_name("JOLI FOU FM (-32.6m SS)"))
        self.assertIsNone(L._caption_name("from trip gas (650 units)"))
        self.assertIsNone(L._caption_name("srtd, fr-g (5%)"))
        self.assertEqual(L._caption_name("Gamma thru casing"), ("Gamma thru casing", "", "gamma"))
        self.assertIsNone(L._caption_name("lower fine grained"))
        for note in ("Butane Test", "Gas detector test", "Gas Maxed", "RPM n/a", "ROTARY INCREASED TO",
                     "Gas lines flooded", "ROP scale change @"):
            self.assertIsNone(L._caption_name(note), note)
        self.assertEqual(L._caption_name("Total Gas (units/10000)")[0], "Total Gas")
        self.assertEqual(L._caption_name("DRILL TIME (min/0.5 m)")[1], "min/0.5 m")
        self.assertEqual(L._caption_name("gamma leg 1 (API)")[0], "gamma leg 1")

    def test_a_reading_by_a_name_is_a_note_not_a_caption(self):
        # a mud check or drilling parameter written down the log ("DEN =
        # 1175", "RPM  0") with numbers by it is no curve's caption
        for note in ("DEN =", "DEN = 1175", "VIS =", "RPM  0", "RPM 0", "RPM           1", "RPM  --",
                     "Mud Type:KCL MUD (Water Based)", "GAS DETECTOR TEST (60s - 1200 units)"):
            self.assertIsNone(L._caption_name(note), note)
        # a curve numbered in its name still is one
        self.assertEqual(L._caption_name("Gas 1")[0], "Gas 1")
        self.assertEqual(L._caption_name("Caliper 2 (mm)")[0], "Caliper 2")
        self.assertEqual(L._caption_name("Gamma 180 (API)")[0], "Gamma 180")

    def test_a_curve_named_for_its_company_alone_is_a_caption(self):
        # "Weatherford" in green over its 0 and 150: a second gamma by the
        # company that ran it; the company in a note is not
        self.assertEqual(L._caption_name("Weatherford"), ("Weatherford", "", None))
        self.assertEqual(L._caption_name("Continental Labs")[0], "Continental Labs")
        for note in ("Weatherford tool failed", "weatherford", "Ryan Energy"):
            self.assertIsNone(L._caption_name(note), note)

    def test_stacked_captions_upright_take_their_own_rows(self):
        # upright: red "100 PROPANE GAS (UNITS) 0" over red "0 TOTAL GAS
        # (UNITS) 500"; the wider 100 above sits nearer TOTAL GAS's middle
        # than its own 0
        doc = fitz.open()
        pg = doc.new_page(width=612, height=792)
        red = (1, 0, 0)
        for x, y, t in ((20.2, 667, "100"), (69.4, 667, "PROPANE GAS (UNITS)"), (181.1, 667, "0"),
                        (20.2, 675, "0"), (73.9, 675, "TOTAL GAS (UNITS)"), (174.6, 675, "500")):
            pg.insert_text((x, y), t, fontsize=6.5, color=red)
        got = {(c.name, c.left, c.right) for c in L.captions(pg, 0, lambda x, y: x)}
        self.assertEqual(got, {("PROPANE GAS", 100.0, 0.0), ("TOTAL GAS", 0.0, 500.0)})
        doc.close()

    def test_a_short_caption_in_a_sideways_decade_stack(self):
        # sideways: 100 10 Deep 1 0.1 down the page in blue, set left at
        # one place (the narrow numbers' middles off the short name's):
        # every decade still the scale's
        doc = fitz.open()
        pg = doc.new_page(width=792, height=612)
        blue = (0, 0, 1)
        for y, t in ((150, "100"), (172, "10"), (188, "Deep"), (204, "1"), (226, "0.1")):
            pg.insert_text((109.4, y), t, fontsize=6.5, color=blue)
        got = [(c.name, c.left, c.right) for c in L.captions(pg, 0, lambda x, y: -y)]
        self.assertEqual(got, [("Deep", 0.1, 100.0)])
        doc.close()

    def test_double_bracket_units(self):
        self.assertEqual(L._caption_name("Neutron ((%))"), ("Neutron", "%", "neutron_porosity"))
        self.assertEqual(L._caption_name("Deep ((ohm/m))"), ("Deep", "ohm/m", "deep_resistivity"))

    def test_a_linear_scale_is_not_followed_out(self):
        # 0 Gas 100 with an unrelated 1000 further along: not a decade series
        doc = fitz.open()
        pg = doc.new_page(width=792, height=612)
        for y, t in ((184, "0"), (168, "Gas (units)"), (152, "100"), (130, "1000")):
            pg.insert_text((400, y), t, fontsize=6, color=(1, 0, 0))
        caps = L.captions(pg, 0, lambda x, y: -y)
        self.assertEqual([(c.name, c.left, c.right) for c in caps], [("Gas", 0.0, 100.0)])
        doc.close()

    def test_a_resistivity_caption_with_one_decade_number(self):
        # upright: a red "0 Total Gas (units) 2000" row, under it a red
        # "Shallow (Ohms)" with only its 10 under the name's end (its ends
        # unprinted); the Total Gas 2000 on its left is no end of its
        doc = fitz.open()
        pg = doc.new_page(width=612, height=792)
        red = (1, 0, 0)
        pg.insert_text((40, 100), "0", fontsize=6.5, color=red)
        pg.insert_text((60, 100), "Total Gas (units)", fontsize=6.5, color=red)
        pg.insert_text((130, 100), "2000", fontsize=6.5, color=red)
        pg.insert_text((181, 120), "Shallow (Ohms)", fontsize=6.5, color=red)
        end = 181 + fitz.get_text_length("Shallow (Ohms)", fontsize=6.5)
        pg.insert_text((end - 2 - fitz.get_text_length("10", fontsize=6.5) / 2, 128), "10", fontsize=6.5, color=red)
        one = []
        caps = L.captions(pg, 0, lambda x, y: x, one)
        self.assertEqual({c.name for c in caps}, {"Total Gas"})
        self.assertEqual([(c.name, c.left, c.right) for c in one], [("Shallow", 10.0, 10.0)])
        self.assertAlmostEqual(one[0].left_at, end - 2, delta=0.5)
        # without a list for them, such a caption is left out
        self.assertEqual({c.name for c in L.captions(pg, 0, lambda x, y: x)}, {"Total Gas"})
        doc.close()

    def test_a_log_scale_s_ends_from_its_grid(self):
        # a one-decade track 146 - 254 (2 - 20), a line at each whole
        # number 3 .. 10, the 10 printed by its line
        per = 108.0
        at = lambda m, x0=146.0, sign=1: x0 + sign * per * math.log10(m / 2)
        grid = [at(m) for m in range(3, 11)] + [10.0, 300.0]       # (other tracks' lines)
        self.assertEqual(M._log_ends_from_grid(grid, 146.0, 254.0, 10.0, at(10) + 2), (2, 20))
        # every other number's line only (4 6 8 10)
        grid = [at(m) for m in (4, 6, 8, 10)]
        self.assertEqual(M._log_ends_from_grid(grid, 146.0, 254.0, 10.0, at(10) + 3), (2, 20))
        # drawn the other way (20 on the left)
        grid = [at(m, 254.0, -1) for m in range(3, 11)]
        self.assertEqual(M._log_ends_from_grid(grid, 146.0, 254.0, 10.0, at(10, 254.0, -1)), (20, 2))
        # an even grid is no log grid
        grid = [146.0 + 10.8 * i for i in range(1, 10)]
        self.assertIsNone(M._log_ends_from_grid(grid, 146.0, 254.0, 10.0, grid[6]))
        # nor are too few lines
        self.assertIsNone(M._log_ends_from_grid([at(m) for m in (5, 10)], 146.0, 254.0, 10.0, at(10)))


@unittest.skipUnless(fitz, "PyMuPDF not installed")
class Lines(unittest.TestCase):
    def test_main_line_inside_the_scale(self):
        got = M.read_line([[0.5], [0.25]], [[-0.5], []], 0, 100)
        self.assertEqual(got, [(50.0, True), (25.0, True)])

    def test_thin_line_past_the_scale(self):
        # 130 on 0..100: main line along the high end, thin line at 30
        got = M.read_line([[1.0]], [[0.3]], 0, 100)
        self.assertAlmostEqual(got[0][0], 130.0)
        self.assertTrue(got[0][1])

    def test_main_line_folded_back_in(self):
        # 95, then 130: the main line drawn back in at 30, the thin line at 30 too
        got = M.read_line([[0.95], [0.3]], [[-0.05], [0.3]], 0, 100)
        self.assertAlmostEqual(got[1][0], 130.0)
        # with nothing above to go by too: the thin line is always one
        # width off the reading, so the two lie together only folded
        self.assertAlmostEqual(M.read_line([[0.3]], [[0.3]], 0, 100)[0][0], 130.0)

    def test_past_twice_the_scale(self):
        got = M.read_line([[1.0]], [[1.7]], 0, 100)
        self.assertAlmostEqual(got[0][0], 270.0)

    def test_a_stray_thin_line_is_not_the_reading(self):
        # the main line says 40; a thin mark at 0.2 (120?) is not borne out
        got = M.read_line([[0.4]], [[0.2]], 0, 100)
        self.assertEqual(got, [(40.0, True)])

    def test_past_the_scale_with_no_thin_line(self):
        self.assertEqual(M.read_line([[1.0]], [[]], 0, 100), [(100, False)])

    def test_thin_line_above_a_reading_below_the_scale(self):
        # -30 on 0..100: main line along the low end, thin line at 70
        got = M.read_line([[0.0]], [[0.7]], 0, 100)
        self.assertAlmostEqual(got[0][0], -30.0)

    def test_lines_together_are_folded(self):
        # 95, then the two lines together at 0.05: 105 (folded in), not 5
        got = M.read_line([[0.95], [0.05]], [[-0.05], [0.05]], 0, 100)
        self.assertAlmostEqual(got[1][0], 105.0)
        # a little apart (drawn in different widths) is still together
        got = M.read_line([[0.95], [0.073]], [[-0.05], [0.062]], 0, 100)
        self.assertAlmostEqual(got[1][0], 106.2, delta=0.1)
        # below the low end already: together is one width lower
        got = M.read_line([[0.0], [0.7]], [[0.7], [0.7]], 0, 100)
        self.assertAlmostEqual(got[1][0], -30.0)

    def test_a_reversed_scale(self):
        # left 10, right 0: 13 sits past the left end
        got = M.read_line([[0.0]], [[0.7]], 10, 0)
        self.assertAlmostEqual(got[0][0], 13.0)

    def test_offset(self):
        main = [[0.2 + 0.01 * i] for i in range(20)]
        self.assertEqual(M._offset(main, [[m[0] - 1] for m in main]), 1)
        self.assertEqual(M._offset(main, [[m[0] + 1] if i % 2 else [m[0] - 1] for i, m in enumerate(main)]), 1)
        self.assertEqual(M._offset(main, [[m[0]] for m in main]), 0)
        self.assertIsNone(M._offset(main, [[0.37 * i % 1.3 - 0.61] for i in range(20)]))

    def test_fill(self):
        self.assertEqual(M._fill([1.0, None, None, 4.0], 0, 0.1), [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(M._fill([1.0] + [None] * 30 + [4.0], 0, 0.1)[5], None)


@unittest.skipUnless(fitz, "PyMuPDF not installed")
class Shelf(unittest.TestCase):
    def test_a_picture_this_legend_leaves_out(self):
        doc = fitz.open(stream=printout(), filetype="pdf")
        every = L.legend(doc, [1])
        strong = next(s for s in every if s.label == "Strong")
        sw = [s for s in every if s.label != "Strong"]
        shelf = {"by_digest": {strong.digest.hex(): {"group": "show", "term": "strong", "px": [8, 8]}}}
        self.assertIsNone(L.Library(sw, doc).find(strong.digest, strong.xref, (8, 8)))
        lib = L.Library(sw, doc, shelf=shelf)
        self.assertEqual(lib.find(strong.digest).term, "strong")
        self.assertEqual(lib.from_shelf, 1)

    def test_runs_down_a_column(self):
        tiles = [(10.0, 10.5, 5, "slide", "directional"), (10.5, 11.0, 5, "slide", "directional"),
                 (12.0, 12.5, 5, "slide", "directional"), (10.0, 11.0, 40, "shale", "rock")]
        self.assertEqual(M.intervals_from_tiles(tiles), [
            {"top": 10.0, "base": 11.0, "group": "directional", "term": "slide"},
            {"top": 12.0, "base": 12.5, "group": "directional", "term": "slide"}])
        self.assertEqual(M.rocks_from_tiles(tiles), [{"top": 10.0, "base": 11.0, "rock": "shale"}])


@unittest.skipUnless(fitz, "PyMuPDF not installed")
class Reading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = M.read(printout())
        cls.marks = K.score(key(), cls.r)

    def test_depth(self):
        self.assertAlmostEqual(self.r["depth"]["top"], TOP, delta=0.01)
        self.assertAlmostEqual(self.r["depth"]["bottom"], BOTTOM, delta=5.01)

    def test_header(self):
        self.assertEqual(self.r["header"].get("well_name"), "TEST 1")

    def test_rocks(self):
        self.assertGreater(self.marks["rocks"]["score"], 0.97)

    def test_symbols(self):
        self.assertEqual(self.marks["symbols"]["score"], 1.0)

    def test_curves(self):
        by = {c["name"]: c for c in self.marks["curves"]["curves"]}
        self.assertGreater(by["ROP"]["score"], 0.97)
        self.assertGreater(by["Gamma"]["score"], 0.97)

    def test_gamma_past_its_scale_read_from_the_thin_line(self):
        g = next(c for c in self.r["curves"] if c["kind"] == "gamma")
        v = K._grid_value(g, 1075.0)
        self.assertAlmostEqual(v, gamma_at(1075.0), delta=1.5)
        self.assertGreater(v, 150)

    def test_rock_patterns_drawn_again_matched_by_look(self):
        r = M.read(printout(redraw_pictures=True), parts=("rocks",))
        marks = K.score(key(), r, ("rocks",))
        self.assertGreater(marks["rocks"]["score"], 0.97)


if __name__ == "__main__":
    unittest.main()
