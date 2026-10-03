"""Canyon: the 2017 sheets whose legend is filled boxes (#771, #772, #773).

97 Canyon filings on the BCER drive include the Painted Pony / UGRBC 2017
sheets (00203, 00213, 00301, 00302, 00313 ...), and every chart page on them
failed "canyon: no calibrated series" on every build since the reader was
written. Two things kept their curves from ever being named:

  - the legend sits 2.2pt ABOVE the panel title, and the reader looked for it
    only below; and
  - each legend sample is a small FILLED box, where the working sheets draw a
    stroked line, and only strokes were asked.

One sheet of them (00301 p39) also prints its time labels in pairs, two
to a text span, which left fewer than three lone labels and no clock.

Naming them then exposed the black series reading the axes: the value
axis's tick marks (left of the frame) and the frame's two corner caps each
gave a black series a point at a labelled value, so Bottom Hole read 0-81 MPa
where the chart draws 36-69.

The page below is built the way 00203 p35 is drawn, coordinates taken from
it, so the whole reader runs on it with no PDF from the corpus.

  python3 -m unittest tests.test_canyon_filled_legend
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz                                               # noqa: E402
import numpy as np                                        # noqa: E402

import canyon                                             # noqa: E402

RED = (1.0, 0.13, 0.07)
BLACK = (0.0, 0.0, 0.0)
X0, X1 = 48.24, 583.92          # 00203's frame
TOP, BOT = 150.24, 312.24       # frame top and the 0 MPa line


def _y(v):                      # 0..80 MPa over the frame, as 00203 rules it
    return BOT - v * (BOT - TOP) / 80.0


def _x(minute):                 # 08:33 at the frame's left, 10 min = 40.3pt
    return X0 + minute * 40.3 / 10.0


def _text_at(page, cx, cy, s, size=8):
    w = fitz.get_text_length(s, fontsize=size)
    page.insert_text((cx - w / 2, cy + size * 0.35), s, fontsize=size)


def _page(filled=True, legend_above=True, paired=False):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((436.6, 24.6), "Ticket #:", fontsize=8)
    page.insert_text((478.0, 24.6), "40-015841", fontsize=8)
    page.insert_text((446.2, 77.0), "Date:", fontsize=8)
    page.insert_text((478.0, 77.0), "2017-08-27", fontsize=8)
    page.insert_text((478.0, 88.6), "#1", fontsize=8)
    title_cy = 142.2
    _text_at(page, 85.2, title_cy, "Pressure (MPa)", 9)
    leg_cy = title_cy - 2.3 if legend_above else title_cy + 1.0
    sh = page.new_shape()
    for name, colour, box_x1 in (("Mainline", RED, 379.4),
                                 ("Bottom Hole", BLACK, 528.8)):
        page.insert_text((box_x1 + 2.0, leg_cy + 3.0), name, fontsize=8)
        r = fitz.Rect(box_x1 - 16.6, leg_cy - 5.3, box_x1, leg_cy + 5.3)
        if filled:
            sh.draw_rect(r)
            sh.finish(color=None, fill=colour)
        else:
            sh.draw_line((r.x0, leg_cy), (r.x1, leg_cy))
            sh.finish(color=colour, width=1.5)
    sh.commit()
    # value ticks: labels left of the frame, black tick marks at 43.2-46.8
    sh = page.new_shape()
    for v in range(0, 81, 10):
        _text_at(page, 35.0, _y(v), str(v))
        sh.draw_line((43.2, _y(v)), (46.8, _y(v)))
    sh.finish(color=BLACK, width=0.5, closePath=False)
    sh.commit()
    # time labels under the frame, 08:33 .. 10:43. 00301 p39 prints the
    # middle ones in pairs, two labels to one text span
    lab = [(_x(10 * i), f"{8 + (33 + 10 * i) // 60:02d}:{(33 + 10 * i) % 60:02d}")
           for i in range(14)]
    if not paired:
        for cx, t in lab:
            _text_at(page, cx, 325.0, t)
    else:
        _text_at(page, lab[0][0], 325.0, lab[0][1])
        _text_at(page, lab[-1][0], 325.0, lab[-1][1])
        w1 = fitz.get_text_length("00:00", fontsize=8)
        for (ca, ta), (cb, tb) in zip(lab[1:-1:2], lab[2:-1:2]):
            gap = (cb - w1 / 2) - (ca + w1 / 2)
            pad = " " * max(1, round(gap / fitz.get_text_length(" ", fontsize=8)))
            page.insert_text((ca - w1 / 2, 325.0 + 8 * 0.35), ta + pad + tb,
                             fontsize=8)
    # the frame: a top rule and a left rule, and its two corner caps, each a
    # one-segment path of its own as 00203 draws them
    sh = page.new_shape()
    sh.draw_line((X0, TOP), (X1, TOP))
    sh.draw_line((X0, TOP), (X0, BOT))
    sh.finish(color=BLACK, width=0.5, closePath=False)
    sh.commit()
    for (a, b), closed in ((((X1, TOP), (X1 + 0.24, TOP)), False),
                           (((X0, BOT + 0.24), (X0 + 0.24, BOT + 0.24)), True)):
        sh = page.new_shape()
        sh.draw_line(a, b)
        sh.finish(color=BLACK, width=0.5, closePath=closed)
        sh.commit()
    # the curves: 130 minutes, Mainline 30 -> 55 MPa, Bottom Hole 40 -> 68
    ts = np.linspace(0, 130, 400)
    for colour, lo, hi in ((RED, 30.0, 55.0), (BLACK, 40.0, 68.0)):
        vals = lo + (hi - lo) * ts / 130.0 + 0.4 * np.sin(ts)
        sh = page.new_shape()
        sh.draw_polyline([(_x(t), _y(v)) for t, v in zip(ts, vals)])
        sh.finish(color=colour, width=0.8, closePath=False)
        sh.commit()
    return doc, page


class FilledLegend(unittest.TestCase):

    def setUp(self):
        self.doc, page = _page()
        self.meta, self.samples, self.data, self.units = canyon.extract_page(page)

    def test_both_curves_are_named(self):
        self.assertEqual(set(self.data), {"Mainline", "Bottom Hole"})
        self.assertEqual(self.units["Bottom Hole"], "MPa")

    def test_the_stage_starts_at_its_frame_not_at_the_axis(self):
        # 08:33 at the frame's left; the tick marks sat 90s earlier
        h, m, s = map(int, self.meta.start_time.split(":"))
        self.assertLess(abs((h * 3600 + m * 60 + s) - (8 * 3600 + 33 * 60)), 15)
        self.assertAlmostEqual(self.meta.duration_min, 130.0, delta=1.0)

    def test_black_series_reads_the_curve_not_the_axis(self):
        v = np.asarray(self.data["Bottom Hole"], float)
        self.assertGreater(np.nanmin(v), 38.0)       # not 0: no bottom cap
        self.assertLess(np.nanmax(v), 70.0)          # not 80: no top cap or tick
        self.assertAlmostEqual(v[60 * 65], 54.0, delta=1.5)

    def test_coloured_series_unchanged_in_kind(self):
        v = np.asarray(self.data["Mainline"], float)
        self.assertAlmostEqual(np.nanmin(v), 30.0, delta=1.5)
        self.assertAlmostEqual(np.nanmax(v), 55.0, delta=1.5)


class LegendSampleChoice(unittest.TestCase):

    def test_a_stroked_sample_still_reads(self):
        doc, page = _page(filled=False, legend_above=False)
        _m, _s, data, _u = canyon.extract_page(page)
        self.assertEqual(set(data), {"Mainline", "Bottom Hole"})

    def test_white_and_large_fills_are_never_a_sample(self):
        doc = fitz.open()
        page = doc.new_page()
        sh = page.new_shape()
        sh.draw_rect(fitz.Rect(10, 10, 26, 20))
        sh.finish(color=None, fill=(1, 1, 1))
        sh.draw_rect(fitz.Rect(10, 30, 200, 300))
        sh.finish(color=None, fill=RED)
        sh.commit()
        for d in page.get_drawings():
            self.assertIsNone(canyon._filled_sample(d))

    def test_paired_time_labels_still_give_a_clock(self):
        doc, page = _page(paired=True)
        lone = [sp for sp in canyon._spans(page)
                if canyon.re.fullmatch(r"\d{1,2}:\d{2}", sp["t"])]
        self.assertEqual(len(lone), 2)            # too few to fit a clock alone
        m, _s, data, _u = canyon.extract_page(page)
        self.assertEqual(m.start_time[:5], "08:33")
        self.assertAlmostEqual(m.duration_min, 130.0, delta=1.5)
        self.assertEqual(set(data), {"Mainline", "Bottom Hole"})

    def test_outside_the_frame(self):
        P = fitz.Point
        f = (X0, X1)
        self.assertTrue(canyon._outside(f, P(43.2, 200), P(46.8, 200)))
        self.assertFalse(canyon._outside(f, P(48.3, 200), P(49.0, 201)))
        self.assertFalse(canyon._outside(None, P(43.2, 200), P(46.8, 200)))


if __name__ == "__main__":
    unittest.main()
