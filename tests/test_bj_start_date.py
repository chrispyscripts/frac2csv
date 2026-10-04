"""A BJ-1 chart is dated by the day it STARTS, not by its first label's day.

  python3 -m unittest tests.test_bj_start_date

bj1 took a chart's date from its first clock label and its start time from
its first curve point. BJ prints the frame a little wider than the labels, so
a stage whose pumps came on just before midnight starts left of a "00:00"
label: 00730 stage 06 prints "Jul-28 00:00" as its first label and its
pressure is up at 23:58, and came out as 2024-07-28 23:58:04 — a day after it
ran, and after stage 07 (Jul-28 04:18). 00730 stage 25 (Aug-03 00:00, starts
23:59:33) and 01249 stage 34 (May-21 00:00, starts 23:58:52) were the same.

The pages here are built the way the template draws one — slanted
"Mon-DD HH:MM" labels on 15-minute gridlines, two stacked axes, a legend —
with a text layer, so no OCR is involved, and the reading is checked against
the instant the curves were DRAWN at.
"""
import datetime
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz                                              # noqa: E402
import numpy as np                                       # noqa: E402

import bj1                                               # noqa: E402

# 01247 p197's geometry: 15-minute gridlines 55.2pt apart, the frame wider
X0, Y_TOP, X1, Y_BOT = 100.7, 197.6, 554.5, 572.3
TICK0, STEP = 131.28, 55.2
SEC_PER_PT = 900.0 / STEP
TITLE = "100/01-26-080-17W6 - Well A - Stage 02"


def _y(v, vmax):
    return Y_BOT - (Y_BOT - Y_TOP) * v / vmax


def _chart(first, start_min, title=TITLE, year_hint=2025):
    """A BJ-1 chart page whose first label reads `first` (a datetime) and
    whose curves start `start_min` minutes from it (negative: before it)."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for x in (X0, X1):                         # the frame's sides, stroked
        sh = page.new_shape()
        sh.draw_line((x, Y_TOP), (x, Y_BOT))
        sh.finish(color=(0, 0, 0), width=0.72)
        sh.commit()
    for k in range(8):
        x = TICK0 + k * STEP
        sh = page.new_shape()
        sh.draw_line((x, Y_TOP + 0.4), (x, Y_BOT))
        sh.finish(color=(0.7, 0.7, 0.7), width=0.72, dashes="[2.28 .96] 0")
        sh.commit()
        label = (first + datetime.timedelta(minutes=15 * k)).strftime("%b-%d %H:%M")
        w = fitz.get_text_length(label, fontname="helv", fontsize=8)
        end = fitz.Point(x - 1.0, Y_BOT + 18)
        at = end + (-w * math.cos(math.radians(30)), w * math.sin(math.radians(30)))
        page.insert_text(at, label, fontsize=8, fontname="helv",
                         morph=(at, fitz.Matrix(30)))
    for k in range(6):
        y = _y(k, 5)
        for txt, right in ((str(20 * k), 52.6), (str(5 * k), 97.9)):
            w = fitz.get_text_length(txt, fontname="helv", fontsize=8)
            page.insert_text((right - w, y + 2.8), txt, fontsize=8, fontname="helv")
    page.insert_text((36.0, 418.0), "WH 2 Press (MPa)", fontsize=8,
                     fontname="helv", rotate=90)
    page.insert_text((85.5, 428.0), "CMB SLR Rate (m3/min)", fontsize=8,
                     fontname="helv", rotate=90)
    page.insert_text((244.2, 193.4), title, fontsize=9, fontname="helv")
    for i, (name, col) in enumerate((("WH 2 Press (MPa)", (1, 0, 0)),
                                     ("CMB SLR Rate (m3/min)", (0, 0, 1)))):
        y = 212.3 + 11.1 * i
        sh = page.new_shape()
        sh.draw_line((435.6, y), (451.0, y))
        sh.finish(color=col, width=1.4)
        sh.commit()
        page.insert_text((457.3, y + 2.8), name, fontsize=8, fontname="helv")
    xa = TICK0 + start_min * 60.0 / SEC_PER_PT
    xs = np.arange(xa, 533.5 + 0.01, 0.5)
    for vmax, col, top in ((100.0, (1, 0, 0), 70.0), (25.0, (0, 0, 1), 10.0)):
        sh = page.new_shape()
        sh.draw_polyline([fitz.Point(x, _y(top * min(1.0, (x - xa) / 60.0), vmax))
                          for x in xs])
        sh.finish(color=col, width=0.72, closePath=False)
        sh.commit()
    if year_hint:
        doc._bj1_year_hint = year_hint
    return doc


def _read(first, start_min, **kw):
    meta, _s, _d, _u = bj1.extract_page(_chart(first, start_min, **kw)[0])
    return meta


def _instant(meta):
    return datetime.datetime.strptime(f"{meta.date} {meta.start_time}",
                                      "%Y-%m-%d %H:%M:%S")


class TheDayIsTheStartsDay(unittest.TestCase):

    def assertStartsAt(self, meta, drawn):
        # the clock is read to the second off a fitted axis: within 20 s of
        # where the curves were drawn, and the DATE is the instant's own
        self.assertAlmostEqual((_instant(meta) - drawn).total_seconds(), 0, delta=20)
        self.assertEqual(meta.date, drawn.date().isoformat())

    def test_curves_up_before_a_midnight_label(self):
        # 00730 stage 06: first label "Jul-28 00:00", pressure up at 23:58
        first = datetime.datetime(2025, 5, 6, 0, 0)
        meta = _read(first, -2)
        self.assertEqual(meta.date, "2025-05-05")
        self.assertTrue(meta.start_time.startswith("23:5"), meta.start_time)
        self.assertStartsAt(meta, first - datetime.timedelta(minutes=2))

    def test_the_day_before_the_first_of_a_month_is_the_real_one(self):
        # the label clock counts every month as 31 days; the day before
        # "Jul-01" is June 30, not a "Jun-31" or a "Jul-00"
        first = datetime.datetime(2025, 7, 1, 0, 0)
        meta = _read(first, -2)
        self.assertEqual(meta.date, "2025-06-30")
        self.assertStartsAt(meta, first - datetime.timedelta(minutes=2))

    def test_the_day_before_new_years_day_is_in_the_year_before(self):
        first = datetime.datetime(2025, 1, 1, 0, 0)
        meta = _read(first, -2)
        self.assertEqual(meta.date, "2024-12-31")
        self.assertStartsAt(meta, first - datetime.timedelta(minutes=2))

    def test_curves_up_after_midnight_past_a_label_before_it(self):
        # the other direction: the first label is the evening before and the
        # curves start after midnight — the chart ran on the later day
        first = datetime.datetime(2025, 5, 5, 23, 45)
        meta = _read(first, 18)
        self.assertEqual(meta.date, "2025-05-06")
        self.assertStartsAt(meta, first + datetime.timedelta(minutes=18))


class AChartThatStartsOnItsLabelsDayIsUnchanged(unittest.TestCase):
    """Every chart whose curves start on its first label's day keeps the
    first label's day, as before."""

    def test_curves_after_the_first_label(self):
        first = datetime.datetime(2025, 5, 5, 18, 0)
        meta = _read(first, 3)
        self.assertEqual(meta.date, "2025-05-05")
        self.assertTrue(meta.start_time.startswith("18:02"), meta.start_time)

    def test_curves_just_before_a_label_that_is_not_midnight(self):
        # the frame is wider than the labels on every chart: starting a
        # little left of the first label is the common case, not the bug
        first = datetime.datetime(2025, 5, 5, 18, 0)
        meta = _read(first, -0.6)
        self.assertEqual(meta.date, "2025-05-05")
        self.assertTrue(meta.start_time.startswith("17:59"), meta.start_time)

    def test_a_chart_that_runs_through_midnight(self):
        # starts in the evening of its first label's day and carries on into
        # the next: dated by its start, which is the label's day
        first = datetime.datetime(2025, 5, 5, 23, 0)
        meta = _read(first, 5)
        self.assertEqual(meta.date, "2025-05-05")
        self.assertTrue(meta.start_time.startswith("23:04"), meta.start_time)

    def test_a_chart_over_new_year(self):
        # "Dec-31 23:30" .. "Jan-01 01:15": the year-rollover push still
        # applies and the start is on the first label's day
        first = datetime.datetime(2025, 12, 31, 23, 30)
        meta = _read(first, 2)
        self.assertEqual(meta.date, "2025-12-31")
        self.assertTrue(meta.start_time.startswith("23:31"), meta.start_time)
        self.assertGreater(meta.duration_min, 100)


class StartDate(unittest.TestCase):
    """bj1._start_date on the label clock: day*86400 + time of day."""

    LABEL = ((7 * 31 + 28) * 86400, 2024, 7, 28)      # "Jul-28 00:00"

    def test_same_day(self):
        s0 = self.LABEL[0]
        self.assertEqual(bj1._start_date(self.LABEL, s0), "2024-07-28")
        self.assertEqual(bj1._start_date(self.LABEL, s0 + 86399.5), "2024-07-28")

    def test_either_side_of_midnight(self):
        s0 = self.LABEL[0]
        self.assertEqual(bj1._start_date(self.LABEL, s0 - 116), "2024-07-27")
        self.assertEqual(bj1._start_date(self.LABEL, s0 + 86400 + 60), "2024-07-29")

    def test_a_first_label_that_is_not_a_date_is_left_alone(self):
        # "Feb-30" is no day at all; extract_page keeps the label's string
        bad = ((2 * 31 + 30) * 86400, 2025, 2, 30)
        self.assertIsNone(bj1._start_date(bad, bad[0] - 60))


class ThroughThePipeline(unittest.TestCase):
    def test_the_exported_chart_carries_the_start_day(self):
        import pipeline
        doc = _chart(datetime.datetime(2025, 5, 6, 0, 0), -2, year_hint=None)
        res, notes = pipeline.extract_document(
            doc, sample_sec=1.0, enable_raster=True,
            filename="01249-102082608017W600_49177_COMP_2025JUL26.PDF")
        series = [r for r in res if r.get("type") == "series"]
        self.assertEqual(len(series), 1, notes)
        self.assertEqual(series[0]["source"], "BJ chart")
        self.assertEqual(series[0]["meta"]["date"], "2025-05-05")
        self.assertTrue(series[0]["meta"]["start_time"].startswith("23:5"))


if __name__ == "__main__":
    unittest.main()
