"""Unit tests for the pure logic — no PDFs, so these run anywhere.

Every case here is a defect this project actually shipped and then fixed. The
point is not coverage; it is that the SPECIFIC mistakes already paid for
cannot come back silently. Each test names the commit or client report it
comes from.

Run: python3 -m pytest tests/ -q      (or: python3 -m unittest discover tests)
"""
import os
import re
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_raster as ar          # noqa: E402
import fitz                       # noqa: E402
import frac_core                  # noqa: E402
import halliburton_ifs as ifs     # noqa: E402
import bj_fracturing as bjf       # noqa: E402
import canyon                     # noqa: E402
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


class TableCsvNaming(unittest.TestCase):
    """Table CSVs were numbered by position, and the position moves between
    wells. Halliburton 00536 prints 14 tables and 00789 prints 13 — the same
    set minus Cluster Data — so -stages-table-13.csv is Cluster Data in one
    well and Stage Description in the other. Batching a folder and reading
    "table-13" from each silently mixed two different tables.
    """

    def test_named_from_the_title(self):
        used = set()
        self.assertEqual(
            localapp.table_csv_name("00536", "Cluster Data (Hal-1)", 12, used),
            "00536-cluster-data-hal-1.csv")

    def test_same_table_gets_the_same_name_in_a_different_well(self):
        # the whole point: position differs, name does not
        a = localapp.table_csv_name("00536", "Stage Description (Hal-1)", 13, set())
        b = localapp.table_csv_name("00789", "Stage Description (Hal-1)", 12, set())
        self.assertEqual(a.split("-", 1)[1], b.split("-", 1)[1])

    def test_duplicate_titles_do_not_overwrite(self):
        used = set()
        first = localapp.table_csv_name("w", "Treatment Log", 0, used)
        second = localapp.table_csv_name("w", "Treatment Log", 1, used)
        self.assertNotEqual(first, second)
        self.assertEqual(second, "w-treatment-log-2.csv")

    def test_untitled_table_falls_back_to_its_index(self):
        self.assertEqual(localapp.table_csv_name("w", "", 4, set()),
                         "w-table-5.csv")
        self.assertEqual(localapp.table_csv_name("w", "///", 0, set()),
                         "w-table-1.csv")

    def test_name_is_filesystem_safe(self):
        nm = localapp.table_csv_name("w", "Avg / Max Technical Data (Hal-1)",
                                     0, set())
        self.assertNotIn("/", nm[1:])
        self.assertEqual(nm, "w-avg-max-technical-data-hal-1.csv")


class TableKind(unittest.TestCase):
    """A Halliburton filing parses 14 tables and they all arrived as an
    undifferentiated list, so "where is the schedule" meant reading every
    title. pipeline.table_kind classifies once, centrally, from the title.
    """

    def test_schedules(self):
        for t in ["Pumping Schedule (design)",          # ifs_tables
                  "Stage Summary (pumped schedule)",    # ifs_tables
                  "Actual Design (pump schedule)",      # hal1_tables, deferred
                  "Job Design"]:                        # Liberty, not parsed yet
            self.assertEqual(pipeline.table_kind(t), "schedule", t)

    def test_schedule_beats_summary_when_the_title_says_both(self):
        # the ordering trap: this one is a schedule with "Summary" in its name
        self.assertEqual(pipeline.table_kind("Stage Summary (pumped schedule)"),
                         "schedule")

    def test_logs(self):
        for t in ["Event log (Hal-1)", "Treatment Log", "Time Log",
                  "TimeTracker Log"]:
            self.assertEqual(pipeline.table_kind(t), "log", t)

    def test_summaries(self):
        for t in ["Proppant Summary (Hal-1)", "Interval summaries",
                  "Totals — per-interval frac summary", "Treatment Details",
                  "Completion Details",
                  "well — per-stage engineering data (Trican)"]:
            self.assertEqual(pipeline.table_kind(t), "summary", t)

    def test_unknown_titles_are_other_not_a_guess(self):
        for t in ["Tubular Data (Hal-1)", "Cluster Data (Hal-1)", "", None]:
            self.assertEqual(pipeline.table_kind(t), "other", str(t))


class CanyonOverviewPage(unittest.TestCase):
    """Canyon prints a per-day OVERVIEW plot covering several stages. Those
    pages carry no depth, so the bare "#N" fallback read each as the FIRST
    stage of its range: 00011 handed back stages 1, 7, 15 and 22 twice, the
    second copy 420/528/414/241 minutes long against a 68-minute median, and
    the Lab merged them by key and drew stage 1 on a 7-hour axis.

    The depth form must keep winning — "#1 - 3689.04m" is a real stage, and
    3689 must never read as the end of a range.
    """

    RANGE = re.compile(r"#\s*(\d+)\s*-\s*(\d+)(?![\d.,])(?!\s*m\b)")

    def _is_overview(self, text):
        m = self.RANGE.search(text)
        return bool(m and int(m.group(2)) > int(m.group(1)))

    def test_ranges_are_overviews(self):
        for t in ["Interval: #1 - 6", "Interval: #7-14",
                  "Interval: #15 - 21", "Interval: #22 - 25"]:
            self.assertTrue(self._is_overview(t), t)

    def test_a_depth_is_not_a_range(self):
        # the trap: "3689" is a plausible second number, ".04m" is what says no
        for t in ["Interval: #1 - 3689.04m", "Interval: #2 - 3638.03m",
                  "Interval: #12 - 3,709.32 m"]:
            self.assertFalse(self._is_overview(t), t)

    def test_bare_stage_is_not_a_range(self):
        # the 2017 layouts print "#1" alone and must keep working
        for t in ["Interval: #1", "#14", "Ticket#: 40-010822"]:
            self.assertFalse(self._is_overview(t), t)

    def test_descending_pair_is_not_a_range(self):
        self.assertFalse(self._is_overview("#6 - 1"))

    def test_the_module_raises_a_distinct_type(self):
        self.assertTrue(issubclass(canyon.NotAStageChart, ValueError))


class IfsDoubledPage(unittest.TestCase):
    """#336 "extreme spikes". Some IFS pages draw the whole chart, paint an
    OPAQUE WHITE rectangle over the plot, and draw it again at a different
    scale. Both copies sit in the content stream with the same colours, same
    clip and full opacity, so the collector saw two of every curve and two of
    every tick column: 181 dips on Treating Pressure on 00002 p339, 178 of
    them a single sample long, against a printed curve that is smooth.

    _axis_columns used to take the LONGEST tick chain. The two label sets have
    the SAME length, so that chose between them arbitrarily and read the peak
    as 81.68 MPa where the page prints 77.9. Given the visible plot box it now
    takes the chain that spans it.
    """

    @staticmethod
    def _labels(values, y_at_zero, y_at_max, cx=90.0):
        # a tick column: value -> cy, linear between the two anchors
        top, bot = float(y_at_max), float(y_at_zero)
        hi = max(values)
        return [{"color": 0, "t": str(v), "cx": cx,
                 "cy": bot - (bot - top) * (v / hi)} for v in values]

    def test_box_picks_the_visible_tick_column(self):
        vals = [0, 20, 40, 60, 80, 100]
        hidden = self._labels(vals, y_at_zero=395.0, y_at_max=130.0)
        visible = self._labels(vals, y_at_zero=469.0, y_at_max=135.2)
        box = fitz.Rect(110.4, 135.2, 642.8, 468.4)      # the last white fill
        cols = ifs._axis_columns(hidden + visible, box)
        self.assertTrue(cols, "no tick column found")
        c = cols[0]
        # value at the box bottom must be ~0 and at its top ~100
        self.assertAlmostEqual(c["a"] + c["b"] * 469.0, 0.0, delta=1.0)
        self.assertAlmostEqual(c["a"] + c["b"] * 135.2, 100.0, delta=1.5)

    def test_without_a_box_behaviour_is_unchanged(self):
        vals = [0, 20, 40, 60, 80, 100]
        cols = ifs._axis_columns(self._labels(vals, 469.0, 135.2), None)
        self.assertTrue(cols)
        self.assertAlmostEqual(cols[0]["a"] + cols[0]["b"] * 469.0, 0.0, delta=1.0)

    def test_a_single_draw_page_hides_nothing(self):
        # one ordinary background fill at the top of the stream: the cut index
        # must not exclude the chart that follows it
        doc = fitz.open()
        page = doc.new_page(width=792, height=612)
        page.draw_rect(fitz.Rect(72, 87, 719, 527), color=None,
                       fill=(1, 1, 1), overlay=True)
        page.draw_line(fitz.Point(120, 200), fitz.Point(600, 210),
                       color=(1, 0, 0))
        cut, box = ifs.visible_plot_box(page)
        n_paths = len(page.get_drawings())
        self.assertLess(cut, n_paths - 1,
                        "the only curve on the page was cut away")
        self.assertIsNotNone(box)
        doc.close()


class GreyPlotFrame(unittest.TestCase):
    """#341 — "No charts extracted, only tables". ARC's Alberta MView pages
    rule their plot box in mid grey (0.5, 0.5, 0.5), and _black_segments only
    accepted near-black, so 00089 p62 yielded ONE segment and _detect_frame
    returned None on a perfectly readable chart. 0 series -> 123.

    The widening is strictly additive and must stay that way: the old rule's
    ink still qualifies, an all-black frame still wins outright, and a dark
    COLOURED curve must never qualify as frame ink.
    """

    def test_near_black_still_qualifies(self):
        for c in [(0.0, 0.0, 0.0), (0.1, 0.1, 0.1), (0.0, 0.0, 0.2)]:
            self.assertTrue(frac_core._frame_ink(c), str(c))

    def test_neutral_grey_now_qualifies(self):
        self.assertTrue(frac_core._frame_ink((0.5, 0.5, 0.5)))

    def test_a_coloured_curve_is_not_frame_ink(self):
        # dark green, dark red: below the level cap but not neutral
        for c in [(0.0, 0.5, 0.0), (0.5, 0.0, 0.0), (0.0, 0.0, 0.5),
                  (0.0, 0.5, 0.5)]:
            self.assertFalse(frac_core._frame_ink(c), str(c))

    def test_light_grey_gridlines_are_not_frame_ink(self):
        for c in [(0.76, 0.76, 0.76), (0.87, 0.87, 0.87), (1.0, 1.0, 1.0)]:
            self.assertFalse(frac_core._frame_ink(c), str(c))


class MviewSurfaceAndBottomHole(unittest.TestCase):
    """MView prints each zone twice — "… Surface" and "… Bottom Hole" — as
    different charts carrying different channels. Both are wanted, but they
    share a zone number and BOTH carry Treating Pressure, so under one key they
    merge and that channel gets two sets of values. Same collision as Canyon's
    overview plot. 00089: 123 series, 61 distinct keys -> 122.
    """

    def test_titles_are_tagged(self):
        cases = [("ARC Resources Ltd 102/02-12-066-25W5/00 Surface", " Surface"),
                 ("ARC Resources Ltd 102/02-12-066-25W5/00 Bottom Hole", " BH"),
                 ("ARC Resources Ltd 102/02-12-066-25W5/00 BottomHole", " BH")]
        for head, want in cases:
            page = type("P", (), {"get_text": lambda self, h=head: h})()
            self.assertEqual(pipeline._mview_variant(page), want, head)

    def test_an_untitled_page_is_left_alone(self):
        page = type("P", (), {"get_text": lambda self: "Zones 1-2"})()
        self.assertEqual(pipeline._mview_variant(page), "")


class LibertyStageKeywordCase(unittest.TestCase):
    """#346 — "Stage ? showed as last stage". ARC's Alberta Liberty filings
    title their charts "MIDDLE MONTNEY - STAGE 2", in caps. The fallback stage
    pattern is deliberately case-SENSITIVE, because it reads a trailing
    ALL-CAPS token as part of the name ("1A HRF"), so it matched neither
    "Stage" nor "STG": 32 of 56 charts on 00269 came back with no stage at all
    and collapsed under one blank key. Only the KEYWORD is case-insensitive.
    """

    def _stage(self, text):
        m = (re.search(rf"{lib1._STAGE}\s+([A-Za-z0-9][A-Za-z0-9\- ]*?)\s+of\s+\d+",
                       text, re.I)
             or re.search(rf"{lib1._STAGE}\s+((?:[A-Z]{{2,4}}\s+)?\d+[A-Z]?"
                          r"(?:\s*-\s*[A-Z]{2,4})?(?:[ \t]+[A-Z]{2,4})?)\b()",
                          text))
        return " ".join(m.group(1).split()) if m else None

    def test_all_caps_stage_is_read(self):
        self.assertEqual(self._stage("MIDDLE MONTNEY - STAGE 2"), "2")

    def test_the_spellings_that_already_worked_still_do(self):
        self.assertEqual(self._stage("OVV HZ SUNRISE F5 Stage 13"), "13")
        self.assertEqual(self._stage("Upper Montney - STG 1"), "1")

    def test_an_all_caps_suffix_is_still_part_of_the_name(self):
        # the reason the pattern cannot simply be given re.I
        self.assertEqual(self._stage("Stage 1A HRF"), "1A HRF")

    def test_lowercase_prose_does_not_invent_a_stage(self):
        self.assertIsNone(self._stage("pumped down the stage seven times"))


class BjFracturingSheets(unittest.TestCase):
    """00058 is 218 pages that reported "No extractable data" for weeks
    (#332, #360, #361). It holds no treatment charts at ALL — zero pages carry
    plotted-curve ink — and 66 pages of BJ "Fracturing-Acidizing Treatment"
    sheets nothing read. The pumped schedule is one row per step, in a text
    layer, needing no OCR: 124 rows across 21 fracs on that file.
    """

    def test_cells_lose_wraps_and_thousands_separators(self):
        self.assertEqual(bjf._cell("1,022.97"), "1022.97")
        self.assertEqual(bjf._cell("Slickwater FRP\n@1"), "Slickwater FRP @1")
        self.assertEqual(bjf._cell(None), "")
        # a name that merely contains digits is not a number
        self.assertEqual(bjf._cell("SAND, WHITE, 40/70"), "SAND, WHITE, 40/70")

    def test_completion_type_drops_the_timing_paragraph(self):
        # the header block merges a cell and the timings ride along
        got = bjf._BLEED.sub("", "Plug & Perf Total Time (hrs): 9.2 "
                                 "Non-Pump Time (hrs): 2.6").strip()
        self.assertEqual(got, "Plug & Perf")

    def test_only_numbered_steps_become_rows(self):
        rows = [["#", "Placement"], ["", "Vol."], ["", "(m3)"],
                ["1", "Acid"], ["2", "Pad"], ["", "carried over"]]
        out = bjf._schedule_rows(rows, 1)
        self.assertEqual([r[0] for r in out], ["1", "2"])
        self.assertTrue(all(len(r) == 12 for r in out))

    def test_a_schedule_header_is_recognised(self):
        self.assertTrue(bjf._is_schedule_head(
            [["#", "Placement", "Fluid System"]]))
        self.assertFalse(bjf._is_schedule_head([["Additive", "Volume", "Unit"]]))
        self.assertFalse(bjf._is_schedule_head([]))


class FrameCandidateCap(unittest.TestCase):
    """#362 — "1-30 not seperated". The candidate lists are capped at 16 a side
    because the pairing is quadratic. On a gridded plot every gridline is the
    SAME length as the frame edge, so "longest first" ranks them arbitrarily:
    on 00090 p65 all 21 qualifying horizontals were 492.3pt and the real top
    edge landed at index 18. The frame lost its top, came out 17% short, and 30
    printed zone times were matched against a 1125-minute window on a chart
    whose axis reads 1350 — so no split was possible and the page was left
    whole. Keeping the two OUTERMOST candidates as well fixes it, because a
    frame's edges ARE the extreme lines.
    """

    @staticmethod
    def _cap(cands):
        keep = cands[:16]
        for extreme in (min(cands, key=lambda s: s[1]),
                        max(cands, key=lambda s: s[1])):
            if extreme not in keep:
                keep.append(extreme)
        return keep

    def test_the_outermost_survive_a_full_cap(self):
        # 21 equal-length gridlines: the real edges are first and last by
        # POSITION, and neither is in the first 16 by order
        cands = [(True, 100.0 + i * 37.0, 0.0, 492.3, False) for i in range(21)]
        cands = cands[5:] + cands[:5]          # arbitrary order, as sorting gives
        keep = self._cap(cands)
        ys = [c[1] for c in keep]
        self.assertIn(min(c[1] for c in cands), ys)
        self.assertIn(max(c[1] for c in cands), ys)

    def test_a_short_list_is_untouched(self):
        cands = [(True, 100.0, 0.0, 400.0, True), (True, 700.0, 0.0, 400.0, True)]
        self.assertEqual(len(self._cap(cands)), 2)

    def test_the_cap_stays_small(self):
        cands = [(True, float(i), 0.0, 400.0, False) for i in range(80)]
        self.assertLessEqual(len(self._cap(cands)), 18)


class LibertyCompanyRename(unittest.TestCase):
    """#372-#375 — four ARC files reporting no extractable data. They ARE
    Liberty; the company renamed. Filings before it print "Liberty Oilfield
    Services LLC", detect required the literal "Liberty Energy", and nothing
    else on the page identifies the template. 00313: 0 series -> 84.
    """

    def test_both_names_detect(self):
        for name in ["Liberty Energy", "Liberty Oilfield Services LLC",
                     "LIBERTY OILFIELD SERVICES", "liberty energy"]:
            self.assertTrue(lib1._LIBERTY.search(name), name)

    def test_an_unrelated_liberty_does_not(self):
        for name in ["Liberty Mutual", "Statue of Liberty", "Libertyville"]:
            self.assertIsNone(lib1._LIBERTY.search(name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
