"""The IFS clock axis, and what is and is not one of its charts.

  python3 -m unittest tests.test_ifs_clock_strip

00973 (Crew Monias B4-17, BCER Spud-2019-2023) is 282 pages with no text
layer at all: every string is drawn as outlines, so every label comes from
OCR. Two things went wrong with that, and neither of them said so.

1. THE AXIS. The full-page OCR pass reads the whole sheet at 200 dpi at one
   turn, and this template prints the axis DATE 7pt under the clock row. On
   p107 — "Interval 1 - Entire Treatment", which prints 06:00, 06:20, 06:40
   and 07:00 — the pass returned 06:20 and 06:40, turned 06:00 into "00-0"
   and lost 07:00 entirely. Two labels do not make an axis, and because the
   pipeline wants three clock labels before it calls the reader at all, the
   interval produced nothing AND no note (#699, #711). Re-reading the label
   band alone, stood up, at 300 dpi, returns all four at confidence 96+.

   The numbers below are that page and p112 as measured, both readings.

2. THE PAGE COUNT. detect() asked only for the "(IFS v" build stamp, which
   this filing prints on all 282 pages. 184 passed and 88 of those then
   failed the axis — but only 105 pages are charts. The rest are a table of
   contents, a treatment summary, and a stage-summary table and a
   service-report form per interval, none of which this module reads or
   should claim to.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz                                              # noqa: E402

import halliburton_ifs as ifs                            # noqa: E402
import ocr_labels                                        # noqa: E402


def sp(t, cx, cy):
    """An OCR'd span, as _spans hands one to the axis reader."""
    return {"t": t, "cx": cx, "cy": cy, "x0": 0.0, "x1": 0.0,
            "color": 0, "ocr": True}


# 00973 p107. The page pass, and the strip pass over the same four labels.
P107_PAGE = [sp("06:20", -502.0, 482.0), sp("06:40", -371.3, 482.0)]
P107_STRIP = [sp("06:00", -632.8, 482.3), sp("06:20", -502.2, 482.3),
              sp("06:40", -371.6, 482.3), sp("07:00", -241.1, 482.3)]
P107_DATE = sp("2021-09-01", -241.4, 489.4)

# 00973 p112, the same chart for Interval 2. Here the page pass did not just
# lose labels, it misread one: "41:00" where the page prints 11:00.
P112_PAGE = [sp("10:40", -489.8, 482.0), sp("41:00", -365.9, 478.3)]
P112_STRIP = [sp("10:20", -614.0, 482.3), sp("10:40", -490.2, 482.3),
              sp("11:00", -366.1, 482.3), sp("11:20", -242.3, 482.3)]


class TimeAxisFromTheStrip(unittest.TestCase):
    def test_the_page_pass_is_one_label_short(self):
        fit, date = ifs._time_axis(P107_PAGE + [P107_DATE])
        self.assertIsNone(fit)
        self.assertEqual(date, "")

    def test_the_strip_fits_the_clock_the_page_prints(self):
        fit, date = ifs._time_axis(P107_STRIP + [P107_DATE])
        self.assertIsNotNone(fit)
        a, b = fit
        # 06:00 at its own label, and 07:00 an hour later at its own
        self.assertAlmostEqual(a + b * -632.8, 6 * 3600, delta=30)
        self.assertAlmostEqual(a + b * -241.1, 7 * 3600, delta=30)
        self.assertEqual(date, "2021-09-01")

    def test_joining_the_two_readings_would_stretch_the_clock(self):
        # Why the strip REPLACES the page pass instead of adding to it. On
        # p112 the union fits 279 seconds to the point where the strip alone
        # fits 9.68 — a chart that runs 84 minutes read as one running 40
        # hours. A misread label is not a second opinion.
        (_a, b_strip), _d = ifs._time_axis(P112_STRIP)
        (_a2, b_union), _d2 = ifs._time_axis(P112_STRIP + P112_PAGE)
        self.assertAlmostEqual(b_strip, 9.68, delta=0.05)
        self.assertGreater(b_union, 100.0)

    def test_the_strip_reads_p112_as_printed(self):
        fit, _date = ifs._time_axis(P112_STRIP)
        a, b = fit
        self.assertAlmostEqual(a + b * -614.0, 10 * 3600 + 20 * 60, delta=30)
        self.assertAlmostEqual(a + b * -242.3, 11 * 3600 + 20 * 60, delta=30)


class ClockStripSpans(unittest.TestCase):
    """Where the band is, where its readings land, and what is thrown out."""

    # p107's plot frame, and the four vertical gridlines inside it that the
    # page draws at its four labelled times (unrotated x).
    BOX = fitz.Rect(122.4, 151.32, 469.32, 680.4)
    GRIDLINES = (-632.4, -502.0, -371.4, -240.8)
    # the same four readings in PAGE coordinates, which is what
    # ocr_labels.rotated_clock_strip returns
    READINGS = [(482.3, 632.8, "06:00"), (482.3, 502.2, "06:20"),
                (482.3, 371.6, "06:40"), (482.3, 241.1, "07:00")]

    def _page(self):
        self.doc = fitz.open()
        return self.doc.new_page(width=612, height=792)

    def tearDown(self):
        doc = getattr(self, "doc", None)
        if doc is not None:
            doc.close()

    def _with_readings(self, readings, rotated=True, box=None, spans=None):
        real = ocr_labels.rotated_clock_strip
        ocr_labels.rotated_clock_strip = lambda page, clip, **kw: readings
        try:
            return ifs._clock_strip_spans(self._page(), rotated,
                                          spans if spans is not None
                                          else P107_PAGE,
                                          self.BOX if box is None else box)
        finally:
            ocr_labels.rotated_clock_strip = real

    def test_a_reading_lands_on_the_gridline_it_labels(self):
        got = self._with_readings(self.READINGS)
        self.assertEqual([s["t"] for s in got],
                         ["06:00", "06:20", "06:40", "07:00"])
        for s, x in zip(got, self.GRIDLINES):
            self.assertAlmostEqual(s["cx"], x, delta=0.5)
        # and on the clock row the page pass found, not the date row below it
        for s in got:
            self.assertAlmostEqual(s["cy"], 482.0, delta=0.5)

    def test_a_misread_hour_is_left_behind(self):
        # 00973 p223: the page prints 19:00 19:20 19:40 20:00 and one crop
        # reads the last as "29:00"
        bad = [(482.3, 632.8, "19:00"), (482.3, 502.2, "19:20"),
               (482.3, 371.6, "19:40"), (482.3, 241.1, "29:00")]
        got = self._with_readings(bad)
        self.assertEqual([s["t"] for s in got], ["19:00", "19:20", "19:40"])

    def test_three_readings_cannot_spare_one(self):
        # 00971 p164 reads "95:20" for 05:20 and has nothing else to check it
        # against, so the page stays a failure rather than inventing an axis
        bad = [(482.3, 493.0, "95:20"), (482.3, 360.7, "05:40"),
               (482.3, 228.5, "06:00")]
        self.assertEqual(self._with_readings(bad), [])

    def test_a_row_that_crosses_midnight_survives_the_guard(self):
        ok = [(482.3, 493.0, "23:40"), (482.3, 360.7, "00:00"),
              (482.3, 228.5, "00:20")]
        self.assertEqual([s["t"] for s in self._with_readings(ok)],
                         ["23:40", "00:00", "00:20"])

    def test_an_upright_chart_is_left_to_the_page_pass(self):
        # the band is placed the way a chart drawn SIDEWAYS places it, which
        # is the layout every OCR'd IFS filing in this corpus uses. Upright is
        # not handled rather than handled untested, so it reads nothing.
        self.assertEqual(self._with_readings(self.READINGS, rotated=False), [])

    def test_the_labels_alone_are_enough_to_place_the_band(self):
        # 00973 p133's plot frame is not found — visible_plot_box returns the
        # page's background fill — and the row is still read, off the two
        # labels the page pass did get
        got = self._with_readings(self.READINGS, box=None)
        self.assertEqual(len(got), 4)

    def test_with_neither_anchor_there_is_no_band(self):
        page = self._page()
        self.assertEqual(ifs._clock_strip_spans(page, True, [], None), [])


class OnlyAChartIsAChart(unittest.TestCase):
    """detect() claims the pages this module reads, not the report."""

    STAMP = ("CREW ENERGY INC  UWI: 100/13-12-081-22W6  "
             "License #: 41210    (IFS v 7)")

    @staticmethod
    def _page(doc, stamp):
        page = doc.new_page(width=612, height=792)
        if stamp:
            page.insert_text(fitz.Point(40, 40), stamp, fontsize=8)
        return page

    @staticmethod
    def _table(page):
        # a stage-summary table: 11 rows of long straight rules, which is all
        # 00973 p106 draws (1,545 paths, not one of them a curve)
        for i in range(12):
            page.draw_line(fitz.Point(60, 100 + 20 * i),
                           fitz.Point(560, 100 + 20 * i), color=(0, 0, 0))
        for i in range(10):
            page.draw_line(fitz.Point(60 + 50 * i, 100),
                           fitz.Point(60 + 50 * i, 340), color=(0, 0, 0))

    @staticmethod
    def _curve(page, n=400):
        pts = [fitz.Point(120 + i * 0.8, 300 + (i % 7) * 3.0)
               for i in range(n)]
        page.draw_polyline(pts, color=(1, 0, 0))

    def test_a_stage_summary_table_is_not_a_chart(self):
        doc = fitz.open()
        page = self._page(doc, self.STAMP)
        self._table(page)
        self.assertFalse(ifs.detect(page),
                         "a table of rules claimed as a chart")
        self.assertLess(ifs._curve_ink(page), ifs._CURVE_INK_MIN)
        doc.close()

    def test_a_chart_is(self):
        doc = fitz.open()
        page = self._page(doc, self.STAMP)
        self._table(page)                 # charts carry frame and grid too
        self._curve(page)
        self.assertTrue(ifs.detect(page), "a chart page was not claimed")
        self.assertGreaterEqual(ifs._curve_ink(page), ifs._CURVE_INK_MIN)
        doc.close()

    def test_curves_without_the_stamp_are_somebody_else_s(self):
        doc = fitz.open()
        page = self._page(doc, "LIBERTY OILFIELD SERVICES   Stage 7 of 40")
        self._curve(page)
        self.assertFalse(ifs.detect(page))
        doc.close()


if __name__ == "__main__":
    unittest.main()
