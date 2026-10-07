"""Carmine's 2026 filings (#792-#795): what changed on the page, and the fix.

Liberty 00068 prints its clock and axis captions in "rich black" #231F20,
not 0, and lib1 knows black as 0 — no time labels on any of 52 pages.
Trican 1's 2026 sheets print the concentration axis in a pale olive the
label classifier did not know, block the rate labels with a curve's stub,
and leave dots of their gridlines in WH Prop Conc's mask where the curve is
hidden.

  python3 -m unittest tests.test_spud_2026
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import lib1                                              # noqa: E402
import trican_charts as tc                               # noqa: E402

SPUD = os.path.expanduser("~/frac-data/BCER-Frac-Spud-2026")


def _pdf(num):
    hits = glob.glob(os.path.join(SPUD, f"{num}-*.pdf"))
    return hits[0] if hits else None


class RichBlack(unittest.TestCase):

    def test_rich_black_is_black(self):
        self.assertTrue(lib1._black(0))
        self.assertTrue(lib1._black(0x231F20))
        self.assertTrue(lib1._black(0x333333))

    def test_a_dark_series_colour_is_not(self):
        self.assertFalse(lib1._black(0x1F3A5F))          # navy
        self.assertFalse(lib1._black(0x5A1010))          # maroon
        self.assertFalse(lib1._black(0x808080))          # grey, not black


class OliveLabels(unittest.TestCase):

    def _col(self, rgb):
        img = np.full((40, 20, 3), 255, int)
        img[5:35, 5:12] = rgb
        return tc._b_group_class(img, 0, 20, 0, 40)

    def test_the_2026_pale_olive_is_conc(self):
        self.assertEqual(self._col((147, 148, 122)), "conc")

    def test_the_older_greens_still_are(self):
        self.assertEqual(self._col((60, 150, 60)), "conc")

    def test_red_and_blue_are_untouched(self):
        self.assertEqual(self._col((220, 40, 40)), "press")
        self.assertEqual(self._col((70, 150, 220)), "rate")


class LoneDots(unittest.TestCase):

    def test_a_one_dot_column_off_the_curve_goes(self):
        sub = np.zeros((100, 30), bool)
        sub[80, :] = True
        sub[80, 15] = False
        sub[40, 15] = True                       # a gridline dot, curve hidden
        py = np.full(30, 80.0)
        py[15] = 40.0
        self.assertEqual(tc._drop_lone_dots(py, sub), 1)
        self.assertTrue(np.isnan(py[15]))

    def test_a_stroke_stays(self):
        sub = np.zeros((100, 30), bool)
        sub[80, :] = True
        sub[40:81, 15] = True                    # a real spike: a tall stroke
        py = np.full(30, 80.0)
        py[15] = 40.0
        self.assertEqual(tc._drop_lone_dots(py, sub), 0)

    def test_a_step_stays(self):
        sub = np.zeros((100, 30), bool)
        sub[80, :15] = True
        sub[40, 15:] = True                      # a hold at a new level
        py = np.r_[np.full(15, 80.0), np.full(15, 40.0)]
        self.assertEqual(tc._drop_lone_dots(py, sub), 0)


def _hm(t):
    h, m = t.split(":")
    return int(h) * 3600 + int(m) * 60


class MinuteLadder(unittest.TestCase):
    """The clock read off the minutes when OCR has lost the hours."""

    def _start(self, fit, x0=59):
        a, b = fit
        t = (a + b * x0) % 86400
        return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}"

    def test_00036_p83_as_ocr_read_it(self):
        # printed 15:45 16:00 16:15 16:30 16:45 17:00, one every ~111 px
        read = ["5:45", "1:00", "16:15", "16:39", "1:45", "17:00"]
        pts = [(_hm(t), 136.5 + 111.0 * i) for i, t in enumerate(read)]
        fit = tc._b_minute_ladder(pts, 59, 791, start_hint=_hm("15:34"))
        self.assertIsNotNone(fit)
        self.assertAlmostEqual(fit[1], 900 / 111.0, places=3)     # 15 min a label
        self.assertEqual(self._start(fit), "15:34")

    def test_00036_p79_one_label_right_in_five(self):
        # printed 11:00 11:10 11:20 11:30 11:40; the third did not read at all
        read = [("7:00", 0), ("13:10", 1), ("7:39", 3), ("11:40", 4)]
        pts = [(_hm(t), 145.0 + 130.0 * k) for t, k in read]
        fit = tc._b_minute_ladder(pts, 59, 791, start_hint=_hm("10:53"))
        self.assertIsNotNone(fit)
        self.assertEqual(self._start(fit), "10:53")

    def test_00028_p180_a_multi_day_axis_that_reads_is_kept(self):
        # 16:00 [7. Jul] 08:00 16:00 [8. Jul] 08:00 16:00, 8 h a label, the
        # day labels unread: the fit spans 56 h and explains every label,
        # so the ladder must not replace it
        read = [("16:00", 0), ("08:00", 2), ("16:00", 3), ("08:00", 5), ("16:00", 6)]
        pts = [(_hm(t), 110.0 + 104.0 * k) for t, k in read]
        fit = tc._b_clock_fit(pts, 59, 791, start_hint=_hm("12:08"))
        self.assertIsNotNone(fit)
        self.assertGreater(fit[1] * (791 - 59), tc.B_STAGE_MAX_S)
        self.assertEqual(tc._b_explained(fit, pts), len(pts))

    def test_the_printed_start_sets_the_hour_over_misread_votes(self):
        # 00034 p77: "20:xx" read as "2:xx" on most labels
        read = [("2:40", 0), ("2:50", 1), ("21:00", 2), ("2:10", 3), ("21:20", 4)]
        pts = [(_hm(t), 150.0 + 120.0 * k) for t, k in read]
        fit = tc._b_minute_ladder(pts, 59, 791, start_hint=_hm("20:35"))
        self.assertIsNotNone(fit)
        self.assertEqual(self._start(fit)[:2], "20")

    def test_too_few_minutes_is_no_answer(self):
        pts = [(_hm("7:13"), 100.0), (_hm("9:47"), 200.0), (_hm("3:02"), 300.0)]
        self.assertIsNone(tc._b_minute_ladder(pts, 59, 791))


@unittest.skipUnless(_pdf("00068"), "the 2026 filings are not on this machine")
class Liberty00068(unittest.TestCase):

    def test_p104_reads_on_its_clock(self):
        import fitz
        page = fitz.open(_pdf("00068"))[103]
        meta = lib1.extract_page(page)[0]
        self.assertEqual(meta.date, "2026-05-19")
        self.assertEqual(meta.start_time, "09:24:00")
        self.assertAlmostEqual(meta.duration_min, 86, delta=1.5)


@unittest.skipUnless(_pdf("00036"), "the 2026 filings are not on this machine")
class Trican00036(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import fitz
        cls.doc = fitz.open(_pdf("00036"))

    def _read(self, pno):
        meta, samples, chans, info = tc.extract_page_b(self.doc[pno - 1])
        return meta, {c["label"]: float(np.nanmax(c["values"])) for c in chans}, info

    def test_conc_is_read_on_its_own_axis_and_matches_the_page(self):
        for pno in (68, 70, 73, 82, 89):
            meta, peak, info = self._read(pno)
            printed = meta["printed"]["conc_max"]
            self.assertFalse(info.get("conc_derived"), pno)
            self.assertIn("DH Prop Conc", peak, pno)
            self.assertAlmostEqual(peak["DH Prop Conc"], printed, delta=0.02 * printed + 2, msg=pno)
            self.assertLess(peak["WH Prop Conc"], printed * 1.1, pno)    # no 598.5

    def test_the_rate_axis_reads_past_the_curve_stub(self):
        for pno in (68, 82, 89):
            meta, peak, info = self._read(pno)
            self.assertIn("WH Slurry Rate", peak, pno)
            self.assertAlmostEqual(peak["WH Slurry Rate"], meta["printed"]["rate_max"], delta=0.3, msg=pno)


if __name__ == "__main__":
    unittest.main()
