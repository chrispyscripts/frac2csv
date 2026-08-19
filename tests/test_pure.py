"""Unit tests for the pure logic — no PDFs, so these run anywhere.

Every case here is a defect this project actually shipped and then fixed. The
point is not coverage; it is that the SPECIFIC mistakes already paid for
cannot come back silently. Each test names the commit or client report it
comes from.

Run: python3 -m pytest tests/ -q      (or: python3 -m unittest discover tests)
"""
import datetime
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
import bj1                        # noqa: E402
import bj_fracturing as bjf       # noqa: E402
import canyon                     # noqa: E402
import hal1                       # noqa: E402
import hal1_tables                # noqa: E402
import lib1                       # noqa: E402
import liberty_summary            # noqa: E402
import localapp                   # noqa: E402
import ocr_labels                 # noqa: E402
import pipeline                   # noqa: E402
import pipeline_export as pe      # noqa: E402
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


class BjWellIdForms(unittest.TestCase):
    """#371 — "there are charts stages for these BJ that are only reporting
    tables". A well is named two ways in this corpus: the prairie DLS grid
    ("100/12-15-081-18W6") and the northeast-BC NTS form
    ("200/C-022-C-094-G-01"). detect required DLS, so an NTS-named filing
    failed on every page: 01215 read 35 chart pages as nothing. 0 series -> 58
    across 29 stages, and the UWI it derives matches the filename exactly.
    """

    def test_both_forms_are_well_ids(self):
        self.assertTrue(bj1._WELL_ID.search("100/12-15-081-18W6"))
        self.assertTrue(bj1._WELL_ID.search("200/C-022-C-094-G-01"))

    def test_prose_and_part_numbers_are_not(self):
        for s in ["no well here", "123/45", "Rate (m3/min)", "2025/01/18"]:
            self.assertIsNone(bj1._WELL_ID.search(s), s)

    def test_the_id_sits_inside_a_title_line(self):
        line = "200/C-022-C-094-G-01 - Well D - Stage 14"
        self.assertTrue(bj1._WELL_ID.search(line))

    def test_the_separator_is_a_slash_or_a_hyphen(self):
        # 00633 titles its charts "100-12-27-079-16W6 - Well D - Stage 03",
        # which matched nothing: its 10 chart pages read as an empty file with
        # no failure note, because detect never fired (#319)
        self.assertTrue(bj1._WELL_ID.search("100-12-27-079-16W6"))
        self.assertTrue(bj1._WELL_ID.search("200-C-022-C-094-G-01"))

    def test_a_plain_date_is_not_a_well_id(self):
        self.assertIsNone(bj1._WELL_ID.search("2025-01-18"))


class WhyNothingCameOut(unittest.TestCase):
    """"No extractable charts or tables found" is true of a scanned daily
    report and true of a broken parser, and nobody can tell them apart from
    the outside — which is most of what the "No extractable data" backlog is.
    #376 is the case: 140 pages, every one a picture, no treatment charts in
    the file at all, reported in the same words a real failure would use.
    """

    class _Page:
        def __init__(self, text="", curves=False):
            self._t, self._c = text, curves

        def get_text(self, *_a):
            return self._t

        def get_drawings(self):
            if not self._c:
                return []
            return [{"color": (1, 0, 0), "fill": None,
                     "items": [("l",)] * 600}]

    READABLE = "Treating Pressure (MPa) Slurry Rate stage 4 of 20"
    # what a Type3 font with no ToUnicode hands back: the page LOOKS fine
    GARBLED = "\x00\x01\x02\x01\x03\x04\x05\x06\x07" * 25

    class _Doc:
        def __init__(self, pages): self._p = pages
        def __getitem__(self, i): return self._p[i]

    def _note(self, pages, raster=True):
        return pipeline._why_nothing(self._Doc(pages), len(pages), raster)

    def test_scanned_with_no_curves_says_picture_and_ocr(self):
        n = self._note([self._Page() for _ in range(140)])
        self.assertIn("no text layer", n)
        self.assertIn("OCR", n)

    def test_text_but_no_curves_says_there_are_no_charts(self):
        # a real daily-report page carries hundreds of characters; the stub
        # this used to pass ("Daily Time Log") is shorter than any page in the
        # corpus and would be judged unreadable, which is the right call
        page = self._Page(text="Daily Time Log  Start Time  End Time  Code "
                               "Comments  Frac Stage 13 pumped as designed")
        self.assertIn("no treatment charts here to miss",
                      self._note([page for _ in range(50)]))

    def test_curves_but_no_text_says_ocr_the_labels(self):
        n = self._note([self._Page(curves=True) for _ in range(50)])
        self.assertIn("OCR of the labels", n)

    def test_the_ordinary_case_still_reports_plainly(self):
        pages = [self._Page(text=self.READABLE, curves=True) for _ in range(20)]
        self.assertTrue(self._note(pages).startswith(
            "No extractable charts or tables found in 20 pages"))

    def test_garbled_chart_text_is_not_a_text_layer(self):
        # 00035/00051: Type3 fonts, no ToUnicode, 200 of 344 chars are control
        # codes. Counting "has text" would call these parseable and hide the
        # real remedy.
        pages = [self._Page(text=self.GARBLED, curves=True) for _ in range(30)]
        n = self._note(pages)
        self.assertIn("OCR of the labels", n)

    def test_a_readable_cover_does_not_excuse_unreadable_charts(self):
        # 00217: the vendor name is on 54 cover sheets and not one readable
        # character is on any of its 167 chart pages. The CHART pages decide.
        pages = ([self._Page(text=self.READABLE) for _ in range(10)]
                 + [self._Page(text="", curves=True) for _ in range(30)])
        n = self._note(pages)
        self.assertIn("OCR of the labels", n)
        self.assertIn("draw plotted curves", n)


class BjLegendAxisSide(unittest.TestCase):
    """#319-#329. The 2022 filings append the axis SIDE to each legend label —
    "CMB SLR Rate (m3/min) (left)", "WH Press (MPa) (outer l.)" — while the
    axis is titled without it. The matcher asks whether the legend name sits
    INSIDE the axis name, and the qualifier makes it longer, so no curve found
    an axis and the page raised "no curves matched" with 3,677 items of blue
    ink on it. 01359: 47 treatment pages, 0 series -> 94.
    """

    SIDE = re.compile(r"\s*\((?:left|right|outer|inner)[^)]*\)\s*$", re.I)

    def _strip(self, name):
        return self.SIDE.sub("", re.sub(r"\s+", " ", name)).strip()

    def test_the_side_comes_off(self):
        for raw, want in [("CMB SLR Rate (m3/min) (left)", "CMB SLR Rate (m3/min)"),
                          ("WH Press (MPa) (outer l.)", "WH Press (MPa)"),
                          ("Density at Perfs (kg/m3) (right)",
                           "Density at Perfs (kg/m3)")]:
            self.assertEqual(self._strip(raw), want)

    def test_the_unit_survives(self):
        # the unit is what tells two curves on one axis apart, so it must NOT
        # be stripped along with the side
        self.assertIn("(m3/min)", self._strip("CMB SLR Rate (m3/min) (left)"))

    def test_a_label_with_no_side_is_untouched(self):
        self.assertEqual(self._strip("WH Press (MPa)"), "WH Press (MPa)")

    def test_only_a_trailing_side_is_stripped(self):
        self.assertEqual(self._strip("Rate (left) (MPa)"), "Rate (left) (MPa)")


class FilenameUwiWins(unittest.TestCase):
    """Carmine, report #517: the UWI printed inside a filing can be an older
    designation for the same hole; the file name is kept against the current
    register. So the file name leads and the printed value is the fallback —
    the reverse of what shipped through v1.1.2."""

    def test_filename_uwi_beats_the_printed_one(self):
        series = [{"meta": {"uwi": "100010203040W500", "stage": "1",
                            "date": "2020-01-01", "start_time": "00:00:00"},
                   "samples": np.array([0.0, 1.0]),
                   "data": {"Tr Press": np.array([1.0, 2.0])},
                   "units": {}, "labels": {}, "source": "CalFrac chart"}]
        m = pe.build_well(series, fallback_uwi="103050108116W600")
        uwis = {row[0] for blk in m["blocks"] for row in blk["rows"]}
        self.assertEqual(uwis, {"103050108116W600"})

    def test_printed_uwi_still_used_when_the_name_carries_none(self):
        series = [{"meta": {"uwi": "100010203040W500", "stage": "1",
                            "date": "2020-01-01", "start_time": "00:00:00"},
                   "samples": np.array([0.0, 1.0]),
                   "data": {"Tr Press": np.array([1.0, 2.0])},
                   "units": {}, "labels": {}, "source": "CalFrac chart"}]
        m = pe.build_well(series, fallback_uwi="")
        uwis = {row[0] for blk in m["blocks"] for row in blk["rows"]}
        self.assertEqual(uwis, {"100010203040W500"})

    def test_table_uwi_column_is_overridden_when_it_holds_one_well(self):
        res = [{"type": "table", "title": "Stimulation Summary",
                "columns": ["UWI", "Stage"],
                "rows": [["100010203040W500", "1"], ["100010203040W500", "2"]]}]
        pipeline._normalise_tables(res, "01574-103050108116W600_47516_COMP.pdf")
        self.assertEqual({r[0] for r in res[0]["rows"]}, {"103050108116W600"})

    def test_a_multi_well_table_keeps_its_own_uwis(self):
        """A pad summary lists several holes. Stamping the file's own UWI over
        that column would merge different wells into one."""
        res = [{"type": "table", "title": "Pad Summary",
                "columns": ["UWI", "Stage"],
                "rows": [["100010203040W500", "1"], ["102010203040W500", "1"]]}]
        pipeline._normalise_tables(res, "01574-103050108116W600_47516_COMP.pdf")
        self.assertEqual({r[0] for r in res[0]["rows"]},
                         {"100010203040W500", "102010203040W500"})


class HourlyTimeAxisIsNotMinutes(unittest.TestCase):
    """#368's neighbours. A Halliburton treatment plot long enough for hour
    ticks labels its axis "08-15 18", and the dash was not in the OCR
    whitelist — so the label arrived as "081518", fell through to the
    plain-number branch and was read as 81,518 MINUTES. Every one of those
    pages reported a ~6-minute treatment (351s, 359s, 388s, 402s on four of
    the 187 plots sampled) for a job the event log times in hours, and the
    curves were resampled onto that fictional axis before export.
    """

    def test_month_day_hour_reads_as_day_and_hour(self):
        # 15th at 18:00, in hal1's own units: day-of-month * 86400 + sod
        self.assertEqual(ar._md_hour("08-15 18".replace(" ", "")),
                         15 * 86400 + 18 * 3600)

    def test_the_dash_may_be_lost_in_ocr(self):
        self.assertEqual(ar._md_hour("081518"), 15 * 86400 + 18 * 3600)

    def test_a_six_digit_number_that_is_not_a_date_is_refused(self):
        # month 12, day 34 — not a date, so not a clock either
        self.assertIsNone(ar._md_hour("123456"))
        self.assertIsNone(ar._md_hour("08-1599"))   # hour 99
        self.assertIsNone(ar._md_hour("99-1518"))   # month 99
        self.assertIsNone(ar._md_hour("0815"))      # too short to be one


class TreatmentPlotStartDateIsReadWhole(unittest.TestCase):
    """#368 — "can we now add in smarts to get the times and dates at least
    on ones like this that have it on the image". The date is printed under
    the axis and nowhere else on the page, and it is matched as the whole
    printed phrase: a bare date floating under a chart could be a tick label.
    """

    def test_the_printed_caption_is_matched(self):
        m = hal1._START_DATE.search("Pump Time (Start Date: 2025-08-30)")
        self.assertEqual(m.groups(), ("2025", "08", "30"))

    def test_a_loose_date_is_not_a_start_date(self):
        self.assertIsNone(hal1._START_DATE.search("2025-08-30"))
        self.assertIsNone(hal1._START_DATE.search("Start Date: 2025-08-30"))


class ChartDatetimeRefusesWhatItCannotCorroborate(unittest.TestCase):
    """#368 — the treatment plots exported dated 2000-01-01 00:00:00 because
    a raster chart's time axis is an origin, not a clock. It can be turned
    into one, but only where the picture and the report agree: a plausible
    wrong date in a CSV is worse than a blank one.
    """

    EV = [{"name": "Start Pumping", "time": "2025-08-30 04:14:08"},
          {"name": "Pump Acid", "time": "2025-08-30 04:16:22"},
          {"name": "ISIP", "time": "2025-08-30 05:47:34"},
          {"name": "Stop Pumping", "time": "2025-08-30 05:50:46"}]

    def test_report_368_gets_its_date_and_time(self):
        # 01282 p212: axis labelled "03:30 04:00 ...", left edge 03:16:07,
        # caption "Pump Time (Start Date: 2025-08-30)"
        got = hal1_tables.chart_datetime(11767.1, "sod", 9733,
                                         datetime.date(2025, 8, 30), self.EV)
        self.assertEqual(got, ("2025-08-30", "03:16:07"))

    def test_an_elapsed_axis_yields_no_clock_at_all(self):
        self.assertEqual(
            hal1_tables.chart_datetime(0.0, "elapsed", 9733,
                                       datetime.date(2025, 8, 30), self.EV),
            (None, None))

    def test_a_chart_that_opened_before_midnight_is_dated_the_day_before(self):
        # 00424 p115: axis "09 00:00 ...", left edge 8th at 23:54, caption
        # says the 9th. The axis names the day, so the left edge wins.
        self.assertEqual(
            hal1_tables.chart_datetime(777287.5, "day_sod", 6932,
                                       datetime.date(2023, 11, 9), None),
            ("2023-11-08", "23:54:48"))

    def test_axis_day_disagreeing_with_the_caption_is_refused(self):
        # axis says the 15th, caption says the 1st: one of the two is misread
        self.assertEqual(
            hal1_tables.chart_datetime(1360678.8, "day_sod", 21080,
                                       datetime.date(2024, 8, 1), None),
            (None, None))

    def test_an_event_log_a_month_away_from_the_caption_is_refused(self):
        far = [{"name": "Start Pumping", "time": "2025-07-30 04:14:08"}] * 4
        self.assertEqual(
            hal1_tables.chart_datetime(11767.1, "sod", 9733,
                                       datetime.date(2025, 8, 30), far),
            (None, None))

    def test_with_no_calendar_anywhere_nothing_is_invented(self):
        self.assertEqual(
            hal1_tables.chart_datetime(11767.1, "sod", 9733, None, None),
            (None, None))


class GarbledTextLayerIsNotATextLayer(unittest.TestCase):
    """00035/00051 (Paramount): 45 chart pages of real vector curves set in a
    Type3 font with no ToUnicode. The page LOOKS fine and extracts as control
    characters, so nothing named the zone, the date, the axes or the curves
    and the whole file reported "no extractable data".
    """

    class _Page:
        def __init__(self, text):
            self._t = text

        def get_text(self, *_a):
            return self._t

    def test_control_characters_are_not_text(self):
        self.assertTrue(ocr_labels.garbled(
            self._Page("\x00\x01\x02\x03\x04\x05\x06\x07" * 40)))

    def test_an_empty_page_has_no_text_layer_either(self):
        self.assertTrue(ocr_labels.garbled(self._Page("")))

    def test_a_readable_chart_is_never_sent_to_ocr(self):
        # the gate every entry point in ocr_labels hangs off: a false True
        # here would render and OCR every page of every filing
        self.assertFalse(ocr_labels.garbled(self._Page(
            "Progress c-B055-B/094-G-08 Bottom Hole  Time (min)  "
            "Pressure (MPa)  Treating Pressure  Zone 4  April 3, 2020")))


class OcrTickColumnsMustBeStraight(unittest.TestCase):
    """An OCR'd tick column becomes an axis full scale, which multiplies
    every value in that channel. "900" read as "9000" at the top of a
    concentration axis does not look wrong in a list of numbers — it looks
    like a bigger axis — so a reading that misses the column's own line is
    thrown away rather than trusted.
    """

    def test_a_tenfold_misread_is_dropped(self):
        pts = [(100.0, 9000.0), (200.0, 800.0), (300.0, 700.0),
               (400.0, 600.0), (500.0, 500.0), (600.0, 400.0)]
        kept = ocr_labels.axis_column_ok(pts)
        self.assertIsNotNone(kept)
        self.assertNotIn(9000.0, [v for _p, v in kept])
        self.assertEqual(max(v for _p, v in kept), 800.0)

    def test_a_clean_column_survives_intact(self):
        pts = [(100.0, 900.0), (200.0, 800.0), (300.0, 700.0),
               (400.0, 600.0), (500.0, 500.0)]
        self.assertEqual(len(ocr_labels.axis_column_ok(pts)), 5)

    def test_numbers_that_are_not_an_axis_are_refused(self):
        # a caption's numbers that wandered into the band
        pts = [(100.0, 20.0), (180.0, 50.0), (260.0, 3.0), (340.0, 2020.0)]
        self.assertIsNone(ocr_labels.axis_column_ok(pts))


class OcrTimeAxisIsFittedNotMaximised(unittest.TestCase):
    """On an OCR'd chart the duration cannot be "the largest label seen": one
    tick the OCR missed shortens the stage — 140 minutes for a 160-minute job
    — and squeezes every curve on the page to match, with nothing in the
    output to show it happened. 00035 p114 loses two of its nine time labels.
    """

    def test_a_missing_last_tick_is_extrapolated_to_the_frame(self):
        # ticks 20..140 at 81pt apart, frame edge one tick beyond the last
        pts = [(681.5, 20.0), (600.8, 40.0), (519.8, 60.0), (438.9, 80.0),
               (357.7, 100.0), (276.8, 120.0), (196.0, 140.0)]
        self.assertEqual(frac_core._fit_time_axis(pts, 115.19), 160)

    def test_the_last_tick_printed_on_the_edge_reads_as_itself(self):
        pts = [(681.5, 20.0), (600.8, 40.0), (519.8, 60.0), (357.7, 100.0),
               (276.8, 120.0), (196.0, 140.0), (115.0, 160.0)]
        self.assertEqual(frac_core._fit_time_axis(pts, 115.19), 160)

    def test_labels_that_do_not_make_a_line_give_no_duration(self):
        pts = [(681.5, 20.0), (600.8, 900.0), (519.8, 3.0), (357.7, 2020.0)]
        self.assertIsNone(frac_core._fit_time_axis(pts, 115.19))



class CalfracVariantPick(unittest.TestCase):
    """Carmine, #550: Calfrac prints each zone twice, as a "Surface" sheet and
    a "Bottom Hole" sheet, and BOTH were exported as stages. His rule: use
    Surface when it carries all four channels, Bottom Hole when Surface has
    only one conc curve. Keeping the two under separate keys is still right —
    both carry Treating Pressure with different values (#341) — this only
    settles which of them IS the stage.
    """

    @staticmethod
    def _s(stage, chans):
        return {"type": "series", "source": "CalFrac chart",
                "meta": {"stage": stage}, "data": {c: [1.0] for c in chans}}

    ALL4 = ("Tr Press", "Slurry Rate", "WH Prop Conc", "BH Prop Conc")
    THIN = ("Tr Press", "Slurry Rate", "WH Prop Conc")

    def test_surface_wins_when_it_has_all_four(self):
        res = [self._s("2 Surface", self.ALL4), self._s("2 BH", self.ALL4)]
        notes = []
        pipeline._pick_variant(res, notes)
        self.assertEqual([r["meta"]["stage"] for r in res], ["2"])
        self.assertEqual(set(res[0]["data"]), set(self.ALL4))

    def test_bottom_hole_wins_when_surface_has_one_conc(self):
        """00100 zone 2: the Surface sheet carries only one conc curve, so the
        reading is on the Bottom Hole sheet."""
        res = [self._s("2 Surface", self.THIN), self._s("2 BH", self.ALL4)]
        notes = []
        pipeline._pick_variant(res, notes)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["stage"], "2")
        self.assertEqual(set(res[0]["data"]), set(self.ALL4))

    def test_a_zone_printed_once_is_left_alone(self):
        """Nothing to choose between, so nothing is renamed or dropped —
        touching these would change every single-sheet Calfrac file."""
        res = [self._s("3 Surface", self.THIN)]
        notes = []
        pipeline._pick_variant(res, notes)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["stage"], "3 Surface")
        self.assertEqual(notes, [])

    def test_other_providers_are_untouched(self):
        res = [{"type": "series", "source": "Liberty chart",
                "meta": {"stage": "2 Surface"}, "data": {"Tr Press": [1.0]}}]
        pipeline._pick_variant(res, [])
        self.assertEqual(res[0]["meta"]["stage"], "2 Surface")

    def test_the_discarded_sheet_is_named_in_the_notes(self):
        res = [self._s("2 Surface", self.THIN), self._s("2 BH", self.ALL4)]
        notes = []
        pipeline._pick_variant(res, notes)
        self.assertTrue(any("kept BH" in n for n in notes), notes)

    def test_each_zone_is_decided_on_its_own_sheets(self):
        res = [self._s("1 Surface", self.ALL4), self._s("1 BH", self.ALL4),
               self._s("2 Surface", self.THIN), self._s("2 BH", self.ALL4)]
        notes = []
        pipeline._pick_variant(res, notes)
        self.assertEqual(sorted(r["meta"]["stage"] for r in res), ["1", "2"])
        # zone 1 kept Surface, zone 2 kept BH
        self.assertEqual(len(res), 2)


class LibertyDatelessTimeAxis(unittest.TestCase):
    """#549: three Liberty files failed "time labels not found" on every chart
    page. The time labels were there — twelve a page, pure black. What was
    missing was the DATE labels a working sheet prints beside them, so every
    time label was skipped for want of a date partner and the axis came out
    empty. These sheets print a bare "Time" axis and no date anywhere.
    """

    @staticmethod
    def _t(text, cy):
        return {"t": text, "cx": 0.0, "cy": float(cy), "color": 0}

    def test_axis_is_fitted_from_clock_labels_alone(self):
        spans = [self._t(x, cy) for x, cy in
                 [("10:00", 100), ("10:30", 200), ("11:00", 300)]]
        ab, date0, _win = lib1._time_axis(spans)
        self.assertIsNotNone(ab)
        a, b = ab
        self.assertAlmostEqual(a + b * 300 - (a + b * 100), 3600.0, places=3)
        self.assertEqual(date0, "")     # not printed, so not invented

    def test_midnight_is_unwrapped(self):
        """00930 p115 runs 22:56 -> 00:10. Evenly spaced here so the fit is
        exact and the assertion is about the rollover, not least squares."""
        spans = [self._t(x, cy) for x, cy in
                 [("23:00", 100), ("23:30", 200), ("00:00", 300), ("00:30", 400)]]
        ab, _d, _w = lib1._time_axis(spans)
        a, b = ab
        span_min = ((a + b * 400) - (a + b * 100)) / 60.0
        self.assertAlmostEqual(span_min, 90.0, delta=0.1)   # not -1350

    def test_direction_is_judged_on_monotonicity_not_rollover_count(self):
        """Read backwards those labels are 00:10, 23:55, 23:26, 22:56 — which
        never steps back by an hour, so a rollover COUNT scores it zero
        against the correct order's one and picks it. That fitted a negative
        slope and made p115 a 926-minute stage against 18-95 for the well."""
        spans = [self._t(x, cy) for x, cy in
                 [("22:56", 100), ("23:26", 200), ("23:55", 300), ("00:10", 400)]]
        ab, _d, _w = lib1._time_axis(spans)
        self.assertGreater(ab[1], 0, "time must increase with cy here")

    def test_dates_still_win_when_the_sheet_prints_them(self):
        """The fallback must not touch the 631 Liberty files that do."""
        spans = [self._t(x, cy) for x, cy in
                 [("10:00", 100), ("10:30", 200), ("11:00", 300)]]
        spans += [{"t": "2022/04/04", "cx": 0.0, "cy": cy, "color": 0}
                  for cy in (100, 200, 300)]
        ab, date0, _w = lib1._time_axis(spans)
        self.assertEqual(date0, "2022-04-04")
        self.assertIsNotNone(ab)

    def test_too_few_labels_still_refuses(self):
        spans = [self._t("10:00", 100), self._t("10:30", 200)]
        self.assertEqual(lib1._time_axis(spans), (None, "", None))


class ChemicalOnlyChartDropped(unittest.TestCase):
    """Carmine, #553: "it is double plotting the stages with the 2nd one being
    the chemical, we should only display OUR TERMS". Liberty and BJ print a
    treatment plot and then a chemical plot on the next page, both captioned
    with the same stage — 01792 has 106 charts for 53 stages, 00627 has 42 for
    21, and every key is doubled. A chart carrying none of the four channels
    is not a second stage.
    """

    @staticmethod
    def _s(stage, chans, source="BJ chart", page=1):
        return {"type": "series", "source": source, "page": page,
                "meta": {"stage": stage}, "data": {c: [1.0] for c in chans}}

    TREAT = ("WH 2 Press", "CMB SLR Rate", "WH Density", "Density at Perfs")
    CHEM = ("Comb FR Ratio",)

    def test_the_chemical_sheet_is_dropped(self):
        res = [self._s("1", self.TREAT, page=187), self._s("1", self.CHEM, page=188)]
        notes = []
        pipeline._drop_chemical_only(res, notes)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["page"], 187)
        self.assertTrue(notes)

    def test_liberty_named_chemicals_too(self):
        res = [self._s("1", ("Treating Pressure", "Slurry Rate"), "Liberty chart", 105),
               self._s("1", ("B487 CONC", "B701 CONC"), "Liberty chart", 106)]
        pipeline._drop_chemical_only(res, [])
        self.assertEqual([r["page"] for r in res], [105])

    def test_a_chemicals_only_well_is_left_whole(self):
        """If NO chart under the key carries a treatment channel there is
        nothing to prefer, so everything is kept — otherwise a chemicals-only
        well would lose every chart it has."""
        res = [self._s("1", ("B487 CONC",), page=1), self._s("1", ("B701 CONC",), page=2)]
        pipeline._drop_chemical_only(res, [])
        self.assertEqual(len(res), 2)

    def test_numpy_values_do_not_break_the_comparison(self):
        """The unit tests used plain lists and passed; the real corpus holds
        numpy arrays, and two charts under one stage can carry identical meta,
        so `in`/remove() reached `samples` and raised "truth value of an array
        is ambiguous". Caught on 01792, not here — hence this test."""
        def s(stage, chans, page):
            return {"type": "series", "source": "BJ chart", "page": page,
                    "meta": {"stage": stage},          # identical on purpose
                    "samples": np.arange(10.0),
                    "data": {c: np.zeros(10) for c in chans}}
        res = [s("1", self.TREAT, 187), s("1", self.CHEM, 188)]
        pipeline._drop_chemical_only(res, [])
        self.assertEqual([r["page"] for r in res], [187])

    def test_a_lone_chart_is_never_touched(self):
        res = [self._s("1", self.CHEM, page=1)]
        pipeline._drop_chemical_only(res, [])
        self.assertEqual(len(res), 1)

    def test_different_stages_do_not_interact(self):
        res = [self._s("1", self.TREAT, page=1), self._s("2", self.CHEM, page=2)]
        pipeline._drop_chemical_only(res, [])
        self.assertEqual(len(res), 2)

    def test_two_treatment_charts_both_survive(self):
        """Calfrac's Surface/BH pair both carry the four channels; choosing
        between those is _pick_variant's job, not this one's."""
        res = [self._s("1", self.TREAT, page=1), self._s("1", self.TREAT, page=2)]
        pipeline._drop_chemical_only(res, [])
        self.assertEqual(len(res), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
