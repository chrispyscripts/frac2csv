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
import localapp                   # noqa: E402
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
