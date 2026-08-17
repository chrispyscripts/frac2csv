"""Unit tests for the pure logic — no PDFs, so these run anywhere.

Every case here is a defect this project actually shipped and then fixed. The
point is not coverage; it is that the SPECIFIC mistakes already paid for
cannot come back silently. Each test names the commit or client report it
comes from.

Run: python3 -m pytest tests/ -q      (or: python3 -m unittest discover tests)
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_raster as ar          # noqa: E402
import frac_core                  # noqa: E402
import lib1                       # noqa: E402
import liberty_summary            # noqa: E402
import localapp                   # noqa: E402
import pipeline                   # noqa: E402
import trican2                    # noqa: E402


class ResampleKeepsSteps(unittest.TestCase):
    """frac_core._resample averaged the two vertices of a step into a
    mid-level point, corrupting both ends of every flat run. Mean ink error
    1.008 -> 0.004, and it was also why CalFrac stages would not separate.
    """

    def test_flat_run_is_not_averaged_away(self):
        # _resample(t_min, values, sample_min): vertices in minutes, then the
        # sample GRID in minutes. A step is TWO vertices at the same instant,
        # one per level: flat at 10 for 5 min, step at t=5, flat at 20.
        t_min = [0.0, 5.0, 5.0, 10.0]
        values = [10.0, 10.0, 20.0, 20.0]
        grid = np.arange(0.0, 11.0, 1.0)
        out = frac_core._resample(t_min, values, grid)
        out = np.asarray(out, float)
        self.assertAlmostEqual(out[0], 10.0, places=6)
        self.assertAlmostEqual(out[4], 10.0, places=6,
                               msg="last sample of the low run was averaged")
        self.assertAlmostEqual(out[5], 20.0, places=6,
                               msg="first sample of the high run was averaged")
        self.assertAlmostEqual(out[-1], 20.0, places=6)
        # and nothing in between invented a ramp
        self.assertTrue(np.all((out <= 20.0 + 1e-9) & (out >= 10.0 - 1e-9)))


class ExportFolderPrecedence(unittest.TestCase):
    """#113 — a destination set in Settings was only ever a FALLBACK, so it
    did nothing whenever the PDF's own folder was writable, and the export
    reported success while the chosen folder stayed empty.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.dest = os.path.join(self.tmp, "dest")
        for d in (self.src, self.dest):
            os.makedirs(d)
        localapp._WRITABLE.clear()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_destination_wins_when_set(self):
        got, _ = localapp.export_folder(self.src, self.dest)
        self.assertEqual(got, self.dest)

    def test_source_used_when_no_destination(self):
        got, _ = localapp.export_folder(self.src, "")
        self.assertEqual(got, self.src)

    def test_readonly_source_still_falls_back(self):
        ro = os.path.join(self.tmp, "ro")
        os.makedirs(ro)
        os.chmod(ro, 0o500)
        try:
            localapp._WRITABLE.clear()
            got, skipped = localapp.export_folder(ro, self.dest)
            self.assertEqual(got, self.dest)
            self.assertEqual(skipped, "")
        finally:
            os.chmod(ro, 0o700)


class TricanYearFromReportSpan(unittest.TestCase):
    """A STAGE INFORMATION cell prints "Feb 10, 10:09 AM" and no year. The
    year comes from the span of dates the report prints about itself. 00156 is
    the case a "use the filing year" rule gets wrong: filed 2019DEC06, printed
    dates 2019-10-19..2020-01-30, job in NOVEMBER 2019.
    """

    def test_parses_the_cell(self):
        self.assertEqual(trican2._parse_start("Feb 10, 10:09 AM"),
                         (2, 10, 10, 9))
        self.assertEqual(trican2._parse_start("Feb 10, 12:05 AM"),
                         (2, 10, 0, 5))    # midnight is 00, not 12
        self.assertEqual(trican2._parse_start("Jul 1, 12:30 PM"),
                         (7, 1, 12, 30))   # noon stays 12
        self.assertIsNone(trican2._parse_start("not a time"))

    def test_year_spanning_new_year(self):
        from datetime import date
        span = [date(2019, 10, 19), date(2020, 1, 30)]
        self.assertEqual(trican2._year_for(11, 14, span), 2019)
        self.assertEqual(trican2._year_for(1, 20, span), 2020)

    def test_no_printed_dates_means_no_guess(self):
        self.assertIsNone(trican2._year_for(2, 10, []))


class OffScaleBlanking(unittest.TestCase):
    """#97 — a curve clipped at the top of its axis was traced as a flat line
    at the axis maximum and exported as though measured. The BOTTOM edge must
    NOT be blanked: concentration legitimately rests at zero there.
    """

    def _mask(self, rows, cols, lit_top=(), lit_bottom=()):
        m = np.zeros((rows, cols), bool)
        m[rows // 2, :] = True                 # a curve across the middle
        for c in lit_top:
            m[0, c] = True
        for c in lit_bottom:
            m[rows - 1, c] = True
        return m

    def test_top_run_is_blanked(self):
        cols = list(range(10, 10 + ar.EDGE_RUN + 3))
        m = self._mask(40, 60, lit_top=cols)
        py = ar.curve_positions(m, edge_blank=True)
        self.assertTrue(np.all(np.isnan(py[cols])),
                        "a clipped run at the top must not export a value")

    def test_bottom_run_is_kept(self):
        cols = list(range(10, 10 + ar.EDGE_RUN + 3))
        m = self._mask(40, 60, lit_bottom=cols)
        py = ar.curve_positions(m, edge_blank=True)
        self.assertTrue(np.all(np.isfinite(py[cols])),
                        "a curve resting at zero is data, not a clip")


class BlackAxisColumn(unittest.TestCase):
    """A black Liberty series used to borrow a colored axis of the same unit,
    because black tick labels are indistinguishable from axis, grid and title
    ink. The borrow is wrong whenever the two axes disagree: 00374's black
    PFR-ZC FR CONC prints 0.00-1.00 across the same span the colored L/m3
    axes use for 0.00-0.50, so every value shipped at HALF size; 01397's
    black Hydr Pressure prints 10..110 running the other way beside a red
    0..100, which pinned a ~19 MPa curve to 90-100.

    lib1._axis_column is the gate that decides a black column is a printed
    axis. It must accept a real one and reject the black numerics that are
    not — or the fit it enables invents a scale.
    """

    @staticmethod
    def _column(values, x0=137.4, pitch=66.7, cy=94.6):
        return [(v, x0 + i * pitch, cy) for i, v in enumerate(values)]

    def test_accepts_a_printed_tick_column(self):
        # 00374 p45: black PFR-ZC FR CONC, six evenly stepped ticks in one row
        self.assertTrue(lib1._axis_column(
            self._column([1.00, 0.80, 0.60, 0.40, 0.20, 0.00])))

    def test_accepts_an_inverted_column(self):
        # 01397: 10..110 increasing DOWN the page — monotonic is enough
        self.assertTrue(lib1._axis_column(
            self._column([10.0, 30.0, 50.0, 70.0, 90.0, 110.0])))

    def test_rejects_scattered_black_numerics(self):
        # page numbers and a well name's digits: same count, different rows
        pts = self._column([1.0, 2.0, 3.0, 4.0])
        pts = [(v, x, cy + i * 40) for i, (v, x, cy) in enumerate(pts)]
        self.assertFalse(lib1._axis_column(pts))

    def test_rejects_uneven_value_steps(self):
        # 0, 1, 2, 10 is not an axis even when the labels line up
        self.assertFalse(lib1._axis_column(self._column([0.0, 1.0, 2.0, 10.0])))

    def test_rejects_uneven_spacing(self):
        pts = self._column([0.0, 0.2, 0.4, 0.6])
        pts[2] = (pts[2][0], pts[2][1] + 25.0, pts[2][2])
        self.assertFalse(lib1._axis_column(pts))

    def test_rejects_too_few_labels(self):
        self.assertFalse(lib1._axis_column(self._column([0.0, 0.5, 1.0])))


class ReExportNotice(unittest.TestCase):
    """The black-axis fix reaches data the client already exported, so the app
    has to say so. This notice is the only place it ever does, and a warning
    that goes quiet is worse than one that was never written — it reads as
    "nothing to worry about". It is built from the named `rescaled` channels
    on purpose: an earlier version parsed the human sentence out of
    `warnings`, which meant rewording that sentence would have switched the
    notice off in silence.
    """

    @staticmethod
    def _series(*rescaled):
        return {"type": "series", "meta": {"rescaled": list(rescaled)}}

    def test_none_when_nothing_was_rescaled(self):
        self.assertIsNone(pipeline._rescaled_note(
            [self._series(), self._series()]))

    def test_names_the_channel_and_counts_its_charts(self):
        note = pipeline._rescaled_note(
            [self._series("PFR-ZC FR CONC")] * 3)
        self.assertIn("PFR-ZC FR CONC (3 charts)", note)
        self.assertTrue(note.startswith("RE-EXPORT NOTICE"))

    def test_singular_for_one_chart(self):
        note = pipeline._rescaled_note([self._series("Hydr Pressure")])
        self.assertIn("Hydr Pressure (1 chart)", note)

    def test_says_multiplying_cannot_fix_an_old_export(self):
        # the factor is x2 / x3 / x4 by page on PFR-ZC and non-constant on
        # Hydr Pressure, so "just multiply it" produces a NEW wrong number
        note = pipeline._rescaled_note([self._series("Hydr Pressure")])
        self.assertIn("not a constant factor", note)

    def test_ignores_tables_and_summaries(self):
        rows = [{"type": "table", "meta": {"rescaled": ["nope"]}},
                {"type": "summary"},
                self._series("Hydr Pressure")]
        note = pipeline._rescaled_note(rows)
        self.assertIn("Hydr Pressure", note)
        self.assertNotIn("nope", note)


class LibertySummaryKinds(unittest.TestCase):
    """Carmine ran 299 Liberty files and got the Summary view on 10.

    Two mechanisms, both fixed: the view was gated on a Liberty CHART having
    extracted, and the sheet names it knew were the old vintage's only. The
    2025 filings print "Time Log", "24 Hour Summary:" and "Completion Field
    Report" and carry no STIMULATION SUMMARY page at all, so every one of them
    came up empty.
    """

    def test_old_vintage_sheets_still_match(self):
        for text, kind in [("STIMULATION SUMMARY\nStage: 1", "stimulation"),
                           ("PROPPANT SUMMARY", "proppant"),
                           ("LIBERTY", "timetracker"),
                           ("Cement Report", "cement")]:
            self.assertEqual(liberty_summary._page_kind(text), kind, text[:20])

    def test_2025_vintage_sheets_match(self):
        for text, kind in [("Time Log\nTime From\nTime To", "timelog"),
                           ("24 Hour Summary:", "dailysummary"),
                           ("24 Hr Summary:", "dailysummary"),
                           ("Completion Field Report", "fieldreport")]:
            self.assertEqual(liberty_summary._page_kind(text), kind, text[:20])

    def test_well_completion_summary_is_not_dropped(self):
        # on the OLD vintage, beside STIMULATION SUMMARY in all 12 files
        # sampled, and it matched nothing before
        self.assertEqual(liberty_summary._page_kind("WELL COMPLETION SUMMARY"),
                         "wellcompletion")

    def test_a_chart_page_is_not_a_summary_sheet(self):
        self.assertIsNone(liberty_summary._page_kind(
            "OVV HZ SUNRISE F5-26-78-17 Stage 13\nLiberty Energy\nPRC"))

    def test_every_kind_has_a_title(self):
        # a kind with no title renders in the Lab as its bare slug
        for kind, _pat in liberty_summary.SUMMARY_KINDS:
            self.assertIn(kind, liberty_summary.KIND_TITLES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
