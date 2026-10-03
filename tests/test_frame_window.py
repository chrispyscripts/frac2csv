"""The export window is the plot FRAME even when OCR loses the last clock
label (00918 p159, stage 14).

  python3 -m unittest tests.test_frame_window

00918 p159 prints three clock labels — 2022/04/30 08:25, 08:55 and 09:25 —
along a frame that runs 98.44..689.30 and is ruled every 59.09pt: ten
intervals, six minutes apiece, one hour end to end. The page carries no text
layer, so every label is OCR'd, and OCR returns only the first two.

_time_axis calibrates on the two frame EDGES and keeps that fit only if a
label sits at each of them. With the last label missing, the far edge is
301pt past the last label OCR got against a tolerance of 28, the fit is
refused, and the window falls back to label_ts — the span BETWEEN THE TWO
LABELS THAT WERE READ. 1800s. Half the sheet.

Everything past 1800s was then thrown away. All four channels on that page
trace ink from -50.8s to 3217.3s — 54 minutes of it — and the export stopped
at 30. Prop Conc came out with a 413.5 kg/m3 maximum against a real peak of
532.7 that the chart reaches in its back half.

Two labels are still enough, because the gridlines are still printed and the
labels still sit on them: snap each label to its own gridline and calibrate on
those. That also fixes the SLOPE, which is the wider damage — a raw two-label
fit ran this axis 5% fast, 6.3939 s/pt against the 6.0903 the ruled geometry
gives, which is a 3778s hour.

The slope goes wrong because Liberty's raw label positions are NOT evenly
spaced while its gridlines are: an interior label is centred on its line, and
the two OUTERMOST are clamped inward to keep their text on the sheet. 00627
p105 has a text layer and measures it exactly — interior labels 2.1 to 2.9pt
off their line, the outer two pulled in 11.3 and 16.3pt. So a label is held to
its line within 0.2 of a gridline spacing, or 0.45 of one at a frame edge where
it is clamped, both under the half-step at which it could belong to a different
line at all.
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib1                                                # noqa: E402

# 00918 p159, in the coordinates extract_page hands _time_axis: the page is
# landscape, so cx and cy are swapped and the clocks spread along cy.
FRAME = (98.4375, 689.302490234375)
GRID = [98.44, 157.64, 216.62, 275.7, 334.79, 393.99, 452.96, 512.16,
        571.13, 630.22]
# 08:25 and 08:55 are the boxes OCR actually returned. 09:25 it never read,
# so its box is MODELLED: the same 7.96pt inset from its own frame edge that
# the first label has from its.
CLOCK_CY = {"08:25": 106.4, "08:55": 387.9, "09:25": 681.3}
DATE_CY = {"08:25": 121.5, "08:55": 403.0, "09:25": 696.4}
HOUR = 3600.0


def spans(*clocks):
    out = []
    for t in clocks:
        out.append({"t": t, "cx": 495.4, "cy": CLOCK_CY[t], "color": 0,
                    "ocr": True})
        out.append({"t": "2022/04/30", "cx": 481.9, "cy": DATE_CY[t],
                    "color": 0, "ocr": True})
    return out


def moved(t, cy):
    """the same page with one clock label dragged off its gridline"""
    out = spans("08:25", "08:55")
    for s in out:
        if s["t"] == t:
            s["cy"] = cy
    return out


class TheWindowIsTheFrame(unittest.TestCase):

    def test_two_labels_still_size_the_window_to_the_printed_hour(self):
        tfit, date, win = lib1._time_axis(spans("08:25", "08:55"), FRAME, GRID)
        self.assertEqual(date, "2022-04-30")
        self.assertIsNotNone(win)
        # the sheet prints 08:25 -> 09:25; 1.4s of that is the gridlines'
        # own unevenness, well inside the minute the labels are rounded to
        self.assertAlmostEqual(win[1] - win[0], HOUR, delta=5)

    def test_the_old_window_was_the_gap_between_the_two_labels(self):
        # what the label-only fallback gave, and what shipped: 30 minutes,
        # because extract_page sizes the window off min/max of the labels
        # whenever _time_axis hands it no frame window at all
        (_a, b), _d, win = lib1._time_axis(spans("08:25", "08:55"), None, None)
        self.assertIsNone(win)
        self.assertAlmostEqual(b * (CLOCK_CY["08:55"] - CLOCK_CY["08:25"]),
                               1800.0, delta=1)

    def test_the_gridlines_fix_the_slope_the_labels_get_wrong(self):
        (a, b), _d, _w = lib1._time_axis(spans("08:25", "08:55"), None, None)
        # raw label boxes: 6.3939 s/pt, which makes the frame a 3778s hour
        self.assertAlmostEqual(b, 6.3939, places=3)
        self.assertAlmostEqual(b * (FRAME[1] - FRAME[0]), 3777.9, delta=1)
        (a2, b2), _d2, _w2 = lib1._time_axis(spans("08:25", "08:55"),
                                             FRAME, GRID)
        self.assertAlmostEqual(b2, 6.0903, places=3)

    def test_every_printed_label_still_reads_its_own_time(self):
        # the guard the snapped fit is kept on, and the reason a mis-snapped
        # label cannot survive it: each label is read AT ITS OWN unsnapped
        # position and has to come back within a minute or so of its own text
        import datetime as dt
        day = (dt.date(2022, 4, 30) - dt.date(2000, 1, 1)).days * 86400
        (a, b), _d, _w = lib1._time_axis(spans("08:25", "08:55"), FRAME, GRID)
        for t in ("08:25", "08:55", "09:25"):
            hh, mm = (int(x) for x in t.split(":"))
            want = day + hh * 3600 + mm * 60
            self.assertAlmostEqual(a + b * CLOCK_CY[t], want,
                                   delta=lib1.FRAME_FIT_TOL, msg=t)

    def test_three_labels_are_unchanged(self):
        # the frame-edge fit already handled this page when OCR read it whole
        _tf, _d, win = lib1._time_axis(spans("08:25", "08:55", "09:25"),
                                       FRAME, GRID)
        self.assertAlmostEqual(win[1] - win[0], HOUR, delta=2)


class TheGuards(unittest.TestCase):

    def test_without_gridlines_the_frame_is_refused(self):
        # the two frame edges alone: both labels snap to the near one, and
        # one anchor cannot fix an axis
        _tf, _d, win = lib1._time_axis(spans("08:25", "08:55"), FRAME, [])
        self.assertIsNone(win)

    def test_two_labels_on_one_gridline_are_refused(self):
        _tf, _d, win = lib1._time_axis(moved("08:55", 120.0), FRAME, GRID)
        self.assertIsNone(win)

    def test_a_label_that_is_not_on_a_gridline_is_refused(self):
        # 410 is 16pt from the 393.99 line, 0.27 of a 59.1pt step: past the
        # 0.2 an interior label is held to, so the page keeps the fit it had
        _tf, _d, win = lib1._time_axis(moved("08:55", 410.0), FRAME, GRID)
        self.assertIsNone(win)

    def test_a_label_a_little_off_its_gridline_is_kept(self):
        # 6pt off is what OCR's own box centring costs; 400 is 6 the other way
        _tf, _d, win = lib1._time_axis(moved("08:55", 400.0), FRAME, GRID)
        self.assertIsNotNone(win)
        self.assertAlmostEqual(win[1] - win[0], HOUR, delta=5)

    def test_no_frame_no_window(self):
        _tf, _d, win = lib1._time_axis(spans("08:25", "08:55"), None, GRID)
        self.assertIsNone(win)


# 00914 p154, stage 3: 11:01, 11:46 and 12:31 down the same landscape template.
# OCR pairs a date with the first two only, so the third never reaches the fit
# and the frame-edge test refuses it exactly as on 00918 p159. Its far label is
# clamped 20.2pt inside the frame edge — the widest clamp in the corpus.
P154_FRAME = (98.4375, 689.4224853515625)
P154_GRID = [98.44, 157.64, 216.74, 275.82, 334.9, 393.99, 453.07, 512.16,
             571.25, 630.34]


def p154(*clocks):
    cy = {"11:01": 106.0, "11:46": 388.4, "12:31": 669.2}
    out = []
    for t in clocks:
        out.append({"t": t, "cx": 495.4, "cy": cy[t], "color": 0, "ocr": True})
        out.append({"t": "2022/04/23", "cx": 481.9, "cy": cy[t] + 15.5,
                    "color": 0, "ocr": True})
    return out


class TheClampedOutermostLabel(unittest.TestCase):

    def test_a_label_clamped_into_the_frame_is_still_on_its_line(self):
        # 12:31 sits 20.2pt inside the far edge — 0.34 of the 59.2pt step, and
        # 185s of time. Held to the 0.2 an INTERIOR label gets, or to a bound
        # in seconds, this page would be refused and left 4.65% fast.
        _tf, _d, win = lib1._time_axis(p154("11:46", "12:31"),
                                       P154_FRAME, P154_GRID)
        self.assertIsNotNone(win)
        self.assertAlmostEqual(win[1] - win[0], 5400.0, delta=10)   # 90 minutes

    def test_the_raw_labels_ran_the_axis_4_65_percent_fast(self):
        # what the page shipped. The outer labels are clamped inward, so a fit
        # through the raw boxes reads 45 minutes across 282.4pt instead of the
        # 295.5 the gridlines rule: 9.5609 s/pt, and extract_page sized the
        # window off the label span at that rate — 5384s of a 5400s stage,
        # with every timestamp inside it stretched to match.
        (_a, b), _d, _w = lib1._time_axis(p154("11:01", "11:46"), None, None)
        self.assertAlmostEqual(b, 9.5609, places=3)
        self.assertAlmostEqual(b * (669.2 - 106.0), 5384.7, delta=1)
        # the gridlines: 45 minutes across 295.4pt, and a 90-minute frame
        (_a2, b2), _d2, _w2 = lib1._time_axis(p154("11:46", "12:31"),
                                              P154_FRAME, P154_GRID)
        self.assertAlmostEqual(b2, 9.1391, places=3)
        self.assertAlmostEqual(b2 * (P154_FRAME[1] - P154_FRAME[0]),
                               5400.0, delta=10)


# 00949 p106, which has a text layer: a ladder stepping 36.7 picks up an
# eleventh line at 462.21, 14.7pt after the tenth, that the chart never drew.
P106_FRAME = (116.70001220703125, 484.260009765625)
P106_GRID = [116.7, 153.48, 190.2, 226.98, 263.76, 300.48, 337.2, 373.98,
             410.76, 447.48, 462.21]
P106_CY = {"07:07": 121.68, "07:29": 186.54, "07:51": 259.86,
           "08:13": 333.78, "08:35": 407.10, "08:57": 471.96}


class TheSpuriousLine(unittest.TestCase):

    def test_a_line_the_chart_never_drew_does_not_take_a_label(self):
        # 08:57 belongs to the frame edge at 484.26 and lands nearer the
        # spurious 462.21, 0.27 of a step from it
        sp = []
        for t, cy in P106_CY.items():
            sp.append({"t": t, "cx": 300.0, "cy": cy, "color": 0})
            sp.append({"t": "2021/07/11", "cx": 300.0, "cy": cy + 9.37,
                       "color": 0})
        _tf, _d, win = lib1._time_axis(sp, P106_FRAME, P106_GRID)
        self.assertIsNone(win)


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/"
                  "00918-104011108015W600_40232_COMP_2022JUN06.pdf")


@unittest.skipUnless(DRIVE, "the BC drive is not mounted")
class OnThePage(unittest.TestCase):

    def test_00918_p159_exports_the_whole_stage(self):
        import fitz
        doc = fitz.open(DRIVE[0])
        meta, samples, data, _units = lib1.extract_page(doc[158])
        self.assertEqual(meta.stage, "14")
        self.assertEqual(meta.date, "2022-04-30")
        self.assertEqual(meta.start_time, "08:25:00")   # the first label, as printed
        # 1800s before this: the window is the frame now, trimmed back to the
        # last sample any channel reaches (3114s of a 3599s frame)
        self.assertGreater(meta.window, 3000)
        self.assertLess(meta.window, HOUR)
        self.assertEqual(len(samples), int(meta.window))
        for name, (lo, hi) in meta.ink.items():
            # t=0 is the frame edge, so no ramp start sits at negative time
            self.assertAlmostEqual(lo, 0.0, delta=1, msg=name)
            self.assertLess(hi, meta.window + 2, name)
            self.assertGreater(hi, 3000, name)


if __name__ == "__main__":
    unittest.main()
