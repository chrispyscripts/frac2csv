"""BJ-1 charts whose labels are glyph OUTLINES, not text (#774).

  python3 -m unittest tests.test_bj_outline

01247-01254 (Ovintiv's 2025 Tower Lake pad) and 00730 (Swan Lake, 2024) are
BJ filings flattened before they were filed: every character on 280-odd pages
is a filled path, one path per glyph, and the chart pages carry no text layer
at all. bj1.detect read an empty page on every chart (90 of them in 01247),
so each chart fell through to the generic vector gate and was "skipped as schematics
or tables that draw like charts", and all nine files reported No extractable
data. There were no spans for the garbled-font path (00575) to crop either.

ocr_labels.outline_spans rebuilds each string from the glyph paths — drawn
one after another, the same ink, each beside the last — and reads it by
redrawing it alone and upright. These tests build a BJ-1 page the way the
template draws one, flatten it the way those filings were flattened (every
glyph to an outline, the frame's sides to filled rectangles) and check the
reading against what the page was DRAWN with, not against another reading.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz                                              # noqa: E402
import numpy as np                                       # noqa: E402

import bj1                                               # noqa: E402
import ocr_labels                                        # noqa: E402

# the chart as drawn: 15-minute gridlines 55.2pt apart from 18:00, the
# geometry of 01247 p197
X0, Y_TOP, X1, Y_BOT = 100.7, 197.6, 554.5, 572.3
TICK0, STEP = 131.28, 55.2                 # 18:00, then every 15 minutes
SEC_PER_PT = 900.0 / STEP
T_FIRST, T_LAST = 121.6, 533.5            # where the curves start and end


def _t(x):
    """Clock seconds of page x."""
    return 18 * 3600 + (x - TICK0) * SEC_PER_PT


def _rate(t):        # m3/min: 0 until 18:05, ramp to 10 by 18:25, then flat
    return float(np.clip((t - (18 * 3600 + 300)) / 1200.0, 0, 1) * 10.0)


def _press(t):       # MPa: 0 until 18:03, ramp to 70 by 18:13, then flat
    return float(np.clip((t - (18 * 3600 + 180)) / 600.0, 0, 1) * 70.0)


def _y(v, vmax):
    return Y_BOT - (Y_BOT - Y_TOP) * v / vmax


def _chart_page(doc):
    page = doc.new_page(width=612, height=792)
    sh = page.new_shape()
    # the frame's four sides as filled rectangles, as the flattened filings
    # draw them — the text-layer twin strokes them
    for r in ((X0, Y_TOP, X0 + 0.72, Y_BOT), (X1 - 0.72, Y_TOP, X1, Y_BOT),
              (X0, Y_TOP, X1, Y_TOP + 0.72), (X0, Y_BOT - 0.72, X1, Y_BOT)):
        sh.draw_rect(fitz.Rect(r))
    sh.finish(fill=(0, 0, 0), color=None)
    sh.commit()
    for k in range(8):                         # gridlines and tick marks
        x = TICK0 + k * STEP
        sh = page.new_shape()
        sh.draw_line((x, Y_TOP + 0.4), (x, Y_BOT))
        sh.finish(color=(0.7, 0.7, 0.7), width=0.72, dashes="[2.28 .96] 0")
        sh.commit()
        sh = page.new_shape()
        sh.draw_line((x, Y_BOT - 6.1), (x, Y_BOT))
        sh.finish(color=(0, 0, 0), width=0.72)
        sh.commit()
        # "May-05 18:00", right end on its tick, turned 30 degrees
        label = "May-05 %02d:%02d" % divmod(18 * 60 + 15 * k, 60)
        w = fitz.get_text_length(label, fontname="helv", fontsize=8)
        end = fitz.Point(x - 1.0, Y_BOT + 18)
        start = end + (-w * math.cos(math.radians(30)), w * math.sin(math.radians(30)))
        page.insert_text(start, label, fontsize=8, fontname="helv",
                         morph=(start, fitz.Matrix(30)))
    for k in range(6):                         # two stacked value axes
        y = _y(k, 5)
        for txt, right in ((str(20 * k), 52.6), (str(5 * k), 97.9)):
            w = fitz.get_text_length(txt, fontname="helv", fontsize=8)
            page.insert_text((right - w, y + 2.8), txt, fontsize=8, fontname="helv")
    page.insert_text((36.0, 418.0), "WH 2 Press (MPa)", fontsize=8,
                     fontname="helv", rotate=90)
    page.insert_text((85.5, 428.0), "CMB SLR Rate (m3/min)", fontsize=8,
                     fontname="helv", rotate=90)
    page.insert_text((244.2, 193.4), "100/01-26-080-17W6 - Well A - Stage 02",
                     fontsize=9, fontname="helv")
    for i, (name, col) in enumerate((("WH 2 Press (MPa)", (1, 0, 0)),
                                     ("CMB SLR Rate (m3/min)", (0, 0, 1)))):
        y = 212.3 + 11.1 * i
        sh = page.new_shape()
        sh.draw_line((435.6, y), (451.0, y))
        sh.finish(color=col, width=1.4)
        sh.commit()
        page.insert_text((457.3, y + 2.8), name, fontsize=8, fontname="helv")
    xs = np.arange(T_FIRST, T_LAST + 0.01, 0.5)
    for fn, vmax, col in ((_press, 100.0, (1, 0, 0)), (_rate, 25.0, (0, 0, 1))):
        sh = page.new_shape()
        pts = [fitz.Point(x, _y(fn(_t(x)), vmax)) for x in xs]
        sh.draw_polyline(pts)
        sh.finish(color=col, width=0.72, closePath=False)
        sh.commit()
    return page


def _outlined(page):
    """The page with every glyph turned into a filled path and no text left
    — what the #774 filings are."""
    svg = page.get_svg_image(text_as_path=True)
    return fitz.open("pdf", fitz.open("svg", svg.encode()).convert_to_pdf())


class _Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = fitz.open()
        _chart_page(cls.src)
        cls.doc = _outlined(cls.src[0])
        cls.page = cls.doc[0]


class TheShape(_Built):
    """What #774's pages are: drawn labels, no text — no OCR needed here."""

    def test_the_flattened_page_has_no_text_layer(self):
        self.assertEqual(self.page.get_text().strip(), "")
        self.assertTrue(bj1.TIME_RE.search(self.src[0].get_text()))

    def test_the_glyphs_regroup_into_their_strings(self):
        groups = ocr_labels.outline_groups(self.page)
        dirs = [g["dir"] for g in groups]
        slanted = [g for g in groups if 0.5 < g["dir"][0] < 0.95]
        # eight clock labels, each one string, each 30 degrees up
        self.assertEqual(len(slanted), 8)
        for g in slanted:
            self.assertAlmostEqual(math.degrees(math.atan2(-g["dir"][1], g["dir"][0])),
                                   30.0, delta=3)
        # the title is one horizontal string, the axis names run up the page
        title = max(groups, key=lambda g: g["n"] if g["dir"] == (1.0, 0.0) else 0)
        self.assertGreater(title["n"], 30)
        self.assertEqual(dirs.count((0.0, -1.0)), 2)

    def test_the_gate_wants_a_slanted_clock(self):
        self.assertTrue(bj1._clock_slant(ocr_labels.outline_groups(self.page)))
        # a page of upright strings alone — a table, a cover — is not read
        upright = [g for g in ocr_labels.outline_groups(self.page)
                   if g["dir"] in ((1.0, 0.0), (0.0, -1.0))]
        self.assertFalse(bj1._clock_slant(upright))

    def test_a_word_over_a_word_is_two_strings(self):
        # 01116's report pages print "Type" over "Sand" 1.2pt apart in one
        # cell, drawn one after the other. Joined, they ran 21 degrees
        # downhill, three of them made a "clock axis", and every such page
        # paid for OCR. Each is its own upright string.
        src = fitz.open()
        page = src.new_page(width=200, height=200)
        for y in (60.0, 100.0, 140.0):
            page.insert_text((33.0, y), "Type", fontsize=6, fontname="helv")
            page.insert_text((33.5, y + 7.6), "Sand", fontsize=8, fontname="helv")
        groups = ocr_labels.outline_groups(_outlined(page)[0])
        self.assertEqual(sorted(g["n"] for g in groups), [4] * 6)
        self.assertTrue(all(g["dir"] == (1.0, 0.0) for g in groups))
        self.assertFalse(bj1._clock_slant(groups))

    def test_a_decimal_point_does_not_break_a_number(self):
        # "5." alone points downhill — the period sits on the baseline — and
        # judged against that the "00" after it was a new string; every tick
        # of 01247's additive axes ("0.375", "1.125") came apart that way
        src = fitz.open()
        page = src.new_page(width=200, height=200)
        for i, t in enumerate(("0.375", "1.125", "5.00")):
            w = fitz.get_text_length(t, fontname="helv", fontsize=8)
            page.insert_text((60.0 - w, 50.0 + 40 * i), t, fontsize=8, fontname="helv")
        groups = ocr_labels.outline_groups(_outlined(page)[0])
        self.assertEqual([g["n"] for g in groups], [5, 5, 4])
        self.assertTrue(all(g["dir"] == (1.0, 0.0) for g in groups))

    def test_a_refused_page_costs_no_ocr(self):
        real = ocr_labels.ar.ocr_boxes
        calls = []
        ocr_labels.ar.ocr_boxes = lambda *a, **k: calls.append(1) or []
        try:
            d = _outlined(self.src[0])          # fresh doc: nothing cached
            got = ocr_labels.outline_spans(d[0], accept=lambda groups: False)
        finally:
            ocr_labels.ar.ocr_boxes = real
        self.assertEqual(got, [])
        self.assertEqual(calls, [])


class ClockGuards(unittest.TestCase):
    def test_an_outlined_label_snaps_to_the_tick_it_names(self):
        # 01247 p197: ink ends 1.9pt short of the 18:00 tick; minor ticks
        # sit 13.8pt either side and are out of reach
        ticks = [117.48, 131.28, 145.08]
        self.assertEqual(bj1._snap_to_tick(129.4, ticks), 131.28)
        self.assertEqual(bj1._snap_to_tick(120.0, ticks), 120.0)   # none in reach

    def test_a_misread_label_is_dropped_not_fitted(self):
        pts = [(18 * 3600 + 900 * k, 131.28 + 55.2 * k, 590.0) for k in range(6)]
        # "18:45" read as "18:43": two minutes off its gridline
        pts[3] = (pts[3][0] - 120, pts[3][1], pts[3][2])
        self.assertEqual(bj1._clock_inliers(pts),
                         [True, True, True, False, True, True])

    def test_two_agreeing_labels_are_not_an_axis(self):
        pts = [(64800, 131.28, 590.0), (65700, 186.48, 590.0),
               (99999, 241.68, 590.0)]
        self.assertEqual(bj1._clock_inliers(pts), [False] * 3)


@unittest.skipUnless(ocr_labels.available(), "tesseract not installed")
class TheReading(_Built):
    """Read through the template and the pipeline, checked against the page
    as it was drawn."""

    def test_detect_fires_on_the_flattened_page(self):
        self.assertTrue(bj1.detect(self.page))

    def test_the_chart_reads_as_drawn(self):
        meta, samples, data, units = bj1.extract_page(self.page)
        self.assertEqual(meta.uwi, "100012608017W600")
        self.assertEqual(meta.stage, "2")
        self.assertEqual(sorted(data), ["CMB SLR Rate", "WH 2 Press"])
        self.assertEqual(units, {"WH 2 Press": "MPa", "CMB SLR Rate": "m3/min"})
        # the curves start before the first gridline and end after the last:
        # the whole of them, not the stretch between gridlines
        h, m, s = (int(v) for v in meta.start_time.split(":"))
        start = h * 3600 + m * 60 + s
        self.assertAlmostEqual(start, _t(T_FIRST), delta=20)
        self.assertAlmostEqual(meta.duration_min * 60,
                               _t(T_LAST) - _t(T_FIRST), delta=60)
        for clock in (18 * 3600 + 600, 18 * 3600 + 1200, 18 * 3600 + 3600,
                      19 * 3600 + 1800):
            i = int(clock - start)
            self.assertAlmostEqual(data["WH 2 Press"][i], _press(clock), delta=1.5)
            self.assertAlmostEqual(data["CMB SLR Rate"][i], _rate(clock), delta=0.4)

    def test_the_pipeline_exports_it(self):
        import pipeline
        res, notes = pipeline.extract_document(
            _outlined(self.src[0]), sample_sec=1.0, enable_raster=True,
            filename="01247-100012608017W600_49175_COMP_2025JUL27.PDF")
        series = [r for r in res if r.get("type") == "series"]
        self.assertEqual(len(series), 1, notes)
        self.assertEqual(series[0]["source"], "BJ chart")
        self.assertEqual(series[0]["meta"]["date"], "2025-05-05")
        self.assertFalse(any("draw like charts" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
