"""A page turned on its side is still a table (#706).

00915-102051208015W600_40229_COMP_2022JUN02.pdf p103 (0-based 102) is the BC
OGC "Frac Fluid and Additive Treatment Report" — the Data Capture workbook,
printed out of Excel. It carries a real text layer, 1855 words and 9930
characters, and frac2csv reported "no table data" on it. Three of the four
files reported that way in the same batch really are pictures of tables.
This one is not: the page is /Rotate 90, every line drawn with dir (0, -1),
and MuPDF hands the span boxes back UNROTATED. Group the words by y and a
spreadsheet COLUMN comes out looking like a page row —

    y=179 -> ['BY', 'Tracer', 'N', 'N', 'N', ...]

— a column letter, its header, then one value per stage. get_text("text")
linearises it differently again (29 row numbers, then 70 column letters, then
the body), which is why reading the flat text says nothing is there.

Measured on that page, and asserted below:

  * 70 printed column letters, A..CC, with Q..S, AJ/AK and AO..AT missing —
    hidden columns, and their data is not on the sheet either.
  * 23 stage rows, in spreadsheet rows 7..29, stages 1..23. (Not 22: rows
    1..6 are the job header and the grid's own heading.)
  * 67 columns survive: three of the 70 are blank top to bottom.
  * stage 1: Toe, Frac, 23-Apr-22 9:48 -> 23-Apr-22 10:58, 70 min, hole vol
    39.72 m3, interval 5368.17/5368.07, plug 5369.17, perforation interval
    "5368.17 - 5368.07", breakdown 39.1, avg 62.6, max 64.5 MPa, PRE-JOB ISIP
    BLANK, ISIP 19.1, gradient 19706.3, rates 7.99/8.74, Slickwater 445,
    FRESH WATER BLANK, H015 4, clean 448.7, injected 474.8, salinity 18.6%,
    TEMPERATURE BLANK, acid 4.0, five proppant cells at 66,000, difference 0,
    max conc 375.
  * stage 19: the only row whose proppant misses design — 10,000 pumped
    against 231,000 designed, difference 221,000. It is the arithmetic that
    proves the six proppant columns are not off by one.
  * stage 23: 330,000 through all five proppant cells and the Difference cell
    EMPTY, which is what the sheet prints.

Two shapes of cell need care and both are asserted on their real geometry:

  * the merged "Perforation Intervals (m)" cell, centred 2.6pt off anchor O,
    which must NOT be split into its three words;
  * the fused span "CO-WC100 ACI-90WL", two neighbouring header cells whose
    ink touches and which MuPDF returns as one span across anchors BB and BC.
    Taken whole it names BB twice and leaves the ACI-90WL column nameless.

And the sheet's own furniture: Excel prints row numbers 1..29 down the left
margin, 13.4pt left of anchor A against a 28pt A-to-B pitch. Row 6's "6" sits
inside the header's ruled band, so a parser that does not throw the margin
away names the first column "Stage 6".

00915 is not one file and the sheet is not always turned. A 1202-file sweep
of both corpora claims 20 pages across 16 filings and every one of them is
this sheet; fourteen are BCER and two AER, and all sixteen are Liberty's.
00919 p108 is the same workbook on the well next door and its page is
/Rotate 0, which is why TheSameSheetPrintedUPRIGHT is here. Across all
sixteen, 374 stage rows, Designed Sand minus Pumped Total comes to the
printed Difference on 372 of 372 rows that print one and End minus Start to
the printed Job Duration on 371 of 374 — six and five columns respectively,
so a shift of one anywhere breaks them. The three that miss are out by whole
days (1440, 1440 and 5760 minutes), which is the sheet contradicting itself:
00461 p75 prints 14-Jan-23 21:26 to 18-Jan-23 22:26 against a duration of 60.

  python3 -m pytest tests/test_ogc_datacapture.py -q
"""
import datetime
import glob
import os
import sys
import unittest

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ogc_datacapture as og                               # noqa: E402

H = 1224.0          # the unrotated page height: display x = H - unrotated y

# The 70 column letters and their display-x, read off p103. Excel centres a
# column's letter on the column, so this IS the column model.
LETTERS = [
    ("A", 33.5), ("B", 61.3), ("C", 90.3), ("D", 111.6), ("E", 128.6),
    ("F", 145.6), ("G", 164.6), ("H", 184.6), ("I", 201.3), ("J", 218.2),
    ("K", 234.5), ("L", 248.5), ("M", 263.0), ("N", 272.0), ("O", 285.0),
    ("P", 302.7), ("T", 317.0), ("U", 332.0), ("V", 345.2), ("W", 356.8),
    ("X", 368.2), ("Y", 380.2), ("Z", 393.9), ("AA", 407.5), ("AB", 422.0),
    ("AC", 436.6), ("AD", 449.8), ("AE", 463.1), ("AF", 476.0),
    ("AG", 489.2), ("AH", 502.1), ("AI", 517.6), ("AL", 532.0),
    ("AM", 542.8), ("AN", 554.4), ("AU", 566.6), ("AV", 579.3),
    ("AW", 593.4), ("AX", 608.7), ("AY", 621.1), ("AZ", 631.1),
    ("BA", 664.4), ("BB", 698.7), ("BC", 710.9), ("BD", 723.0),
    ("BE", 735.1), ("BF", 747.2), ("BG", 759.3), ("BH", 771.5),
    ("BI", 782.5), ("BJ", 792.5), ("BK", 802.4), ("BL", 812.4),
    ("BM", 822.4), ("BN", 832.4), ("BO", 844.7), ("BP", 880.0),
    ("BQ", 921.0), ("BR", 943.1), ("BS", 961.1), ("BT", 977.7),
    ("BU", 992.0), ("BV", 1005.7), ("BW", 1019.3), ("BX", 1031.7),
    ("BY", 1044.3), ("BZ", 1059.0), ("CA", 1074.3), ("CB", 1089.6),
    ("CC", 1105.0),
]

# The sheet's horizontal cell borders, as p103 draws them: the job header's
# boxes, then the grid's heading band 83.8..97.9, then one band per stage.
RULES = ([54.2, 56.9, 60.4, 63.9, 67.4, 75.4, 83.8, 97.9]
         + [107.0 + 9.1 * i for i in range(23)])

# (display y, x0, x1, text) for the columns this fixture draws, exactly as
# they come off p103: the row-number margin, the stacked heading, and stages
# 1..3 in A, B, L, the merged perforation cell, AY, BB/BC and BS.
CELLS = [
    (86.73, 619.0, 623.9, "Max"),
    (86.73, 1053.2, 1065.1, "Radioactive"),
    (88.17, 242.3, 255.1, "Bridge Plug"),
    (89.49, 618.6, 624.1, "Prop"),
    (89.49, 952.2, 970.6, "ACID PRESSURE"),
    (89.49, 1055.8, 1062.7, "Tracer"),
    (90.81, 269.8, 295.2, "Perforation Intervals (m)"),
    (90.93, 30.5, 36.4, "Stage"),
    (90.93, 52.0, 70.6, "Stage Description"),
    (90.93, 243.2, 254.2, "Set Depth"),
    (90.93, 693.1, 715.9, "CO-WC100 ACI-90WL"),
    (92.25, 618.4, 624.4, "Conc"),
    (92.25, 958.0, 964.2, "DROP"),
    (92.25, 1055.0, 1063.4, "Element"),
    (93.69, 246.7, 250.2, "(m)"),
    (95.01, 617.4, 624.7, "(KgPA)"),
    (95.01, 1055.4, 1062.4, "Isotope"),
    (96.35, 19.6, 20.7, "6"),                   # the row-number margin
    (102.45, 32.9, 34.1, "1"),
    (102.45, 59.3, 63.1, "Toe"),
    (102.45, 244.5, 252.3, "5369.17"),
    (102.45, 273.7, 291.2, "5368.17 - 5368.07"),
    (102.45, 619.3, 622.9, "375"),
    (102.45, 698.2, 699.4, "0"),
    (102.45, 710.3, 711.5, "0"),
    (102.45, 959.6, 962.6, "1.7"),
    (105.47, 19.6, 20.7, "7"),
    (111.57, 32.9, 34.1, "2"),
    (111.57, 59.2, 63.2, "PnP"),
    (111.57, 244.5, 252.3, "5359.00"),
    (111.57, 273.7, 291.2, "5350.37 - 5242.07"),
    (111.57, 619.3, 622.9, "425"),
    (111.57, 698.2, 699.4, "0"),
    (111.57, 710.3, 711.5, "0"),
    (111.57, 959.0, 963.2, "10.0"),
    (114.59, 19.6, 20.7, "8"),
    (120.69, 32.9, 34.1, "3"),
    (120.69, 59.2, 63.2, "PnP"),
    (120.69, 244.6, 252.4, "5233.00"),
    (120.69, 272.5, 292.4, "5224.3748 - 5116.07"),
    (120.69, 619.3, 622.9, "475"),
    (120.69, 696.4, 701.2, "3000"),
    (120.69, 710.3, 711.5, "0"),
    (120.69, 959.0, 963.2, "12.0"),
    (123.71, 19.6, 20.7, "9"),
    (132.83, 19.6, 20.7, "10"),
    (141.95, 19.6, 20.7, "11"),
]

# Word boxes inside the two cells that MuPDF returns as one span. A span's own
# box cannot say where the words inside it sit, and that is what decides
# whether it comes apart.
WORDS = {
    "CO-WC100 ACI-90WL": [(693.1, 704.3, "CO-WC100"),
                          (705.7, 715.9, "ACI-90WL")],
    "Perforation Intervals (m)": [(269.8, 281.4, "Perforation"),
                                  (282.0, 291.1, "Intervals"),
                                  (291.7, 295.2, "(m)")],
    "5368.17 - 5368.07": [(273.7, 281.5, "5368.17"), (282.1, 282.8, "-"),
                          (283.4, 291.2, "5368.07")],
    "5350.37 - 5242.07": [(273.7, 281.5, "5350.37"), (282.1, 282.8, "-"),
                          (283.4, 291.2, "5242.07")],
    "5224.3748 - 5116.07": [(272.5, 282.7, "5224.3748"),
                            (283.3, 284.0, "-"), (284.6, 292.4, "5116.07")],
}

# The stamp and the heading labels p103 prints, as its flat text carries them.
# The fixture above draws only the columns it asserts on; these are the rest
# of the same page's own strings, and they are what detection reads.
STAMP = "Data\xa0Capture\xa0version\xa01.33"
LABELS = ("Stage Description\nJob Duration\nHole Vol\nInterval Bottom\n"
          "Interval Top\nBridge Plug\nPerforation Intervals\nAvg. Press\n"
          "Pre-Job\nAvg. Rate\nMax. Rate\nFluid Type\nTotal Clean\n"
          "Base Fluid\nAcid Type\nTotal Pump Time\n")
SHEET_TEXT = (STAMP + "\n"
              + "FOR USE WITH TREATMENT REPORT VERSION 1.31  OR NEWER ONLY\n"
              + LABELS)


class _Page(object):
    """p103's geometry, put back on its side.

    The fixture is written the way the sheet READS — display x across and
    display y down — and handed back the way MuPDF hands it over, in the
    unrotated space of a /Rotate 90 page: unrotated (x, y) is (display y,
    H - display x). A parser that forgets page.rotation_matrix therefore
    sees a stage as a page column and finds nothing, which is #706 exactly.
    """

    rotation = 90
    rotation_matrix = fitz.Matrix(0, 1, -1, 0, H, 0)

    def __init__(self, cells=CELLS, letters=LETTERS, rules=RULES,
                 text=SHEET_TEXT, height=2.0):
        self._cells = list(cells)
        for name, cx in letters:
            self._cells.append((55.55, cx - 1.3, cx + 1.3, name))
        self._rules = list(rules)
        self._text = text
        self._h = height

    def _box(self, x0, x1, cy):
        """display box -> unrotated box."""
        return (cy - self._h / 2, H - x1, cy + self._h / 2, H - x0)

    def get_text(self, kind="text", **kw):
        if kind == "text":
            return self._text
        if kind == "dict":
            return {"blocks": [
                {"lines": [{"dir": (0.0, -1.0),
                            "spans": [{"text": t,
                                       "bbox": self._box(x0, x1, cy)}]}]}
                for cy, x0, x1, t in self._cells]}
        if kind == "words":
            out = []
            for cy, x0, x1, t in self._cells:
                for a, b, w in WORDS.get(t, [(x0, x1, t)]):
                    out.append(self._box(a, b, cy) + (w, 0, 0, 0))
            return out
        raise AssertionError(kind)

    def get_drawings(self):
        """the cell borders, drawn the way Excel draws them: hairline rects
        running the width of the sheet, 20.0 to 1112.0 across."""
        return [{"items": [("re", fitz.Rect(y - 0.25, H - 1112.0,
                                            y + 0.25, H - 20.0))]}
                for y in self._rules]


class _Doc(object):
    def __init__(self, pages):
        self._pages = list(pages)
        self.page_count = len(self._pages)

    def __getitem__(self, i):
        return self._pages[i]


def _named(tab, name):
    return tab["rows"][0][tab["columns"].index(name)]


def _clock_mismatches(tab):
    """[(stage, measured minutes, printed Job Duration)] where the row's own
    start and end clock does not come to the duration it prints."""
    i = {c: n for n, c in enumerate(tab["columns"])}
    bad = []
    for row in tab["rows"]:
        def at(c):
            return row[i[c]]
        try:
            t0 = datetime.datetime.strptime(
                at("Start Date") + " " + at("Start Time"), "%d-%b-%y %H:%M")
            t1 = datetime.datetime.strptime(
                at("End Date") + " " + at("End Time"), "%d-%b-%y %H:%M")
            mins = (t1 - t0).total_seconds() / 60.0
            printed = float(at("Job Duration"))
        except (KeyError, ValueError) as e:
            bad.append((at("Stage"), repr(e), None))
            continue
        if abs(mins - printed) > 1.0:
            bad.append((at("Stage"), mins, printed))
    return bad


class TheSheetStandsUp(unittest.TestCase):
    """parse_page on p103's own geometry."""

    def setUp(self):
        self.tab = og.parse_page(_Page())
        self.assertIsNotNone(self.tab, "the turned sheet parsed as nothing")

    def test_a_stage_is_a_row_not_a_column(self):
        self.assertEqual([r[0] for r in self.tab["rows"]], ["1", "2", "3"])

    def test_the_row_number_margin_is_not_the_stage_column(self):
        """Row 6's "6" sits inside the heading's ruled band, 13.4pt left of
        anchor A. Kept, it names the first column "Stage 6"."""
        self.assertEqual(self.tab["columns"][0], "Stage")
        self.assertNotIn("6", self.tab["columns"][0])

    def test_a_wrapped_heading_reads_top_to_bottom(self):
        self.assertIn("Bridge Plug Set Depth (m)", self.tab["columns"])
        self.assertIn("Max Prop Conc (KgPA)", self.tab["columns"])
        self.assertIn("ACID PRESSURE DROP", self.tab["columns"])
        self.assertIn("Radioactive Tracer Element Isotope",
                      self.tab["columns"])

    def test_a_merged_cell_is_one_cell(self):
        """"Perforation Intervals (m)" is centred 2.6pt off anchor O and its
        three words land on N, O and P. It is one column, not three."""
        i = self.tab["columns"].index("Perforation Intervals (m)")
        self.assertEqual([r[i] for r in self.tab["rows"]],
                         ["5368.17 - 5368.07", "5350.37 - 5242.07",
                          "5224.3748 - 5116.07"])

    def test_a_fused_span_is_two_cells(self):
        """MuPDF returns "CO-WC100 ACI-90WL" as ONE span across BB and BC."""
        cols = self.tab["columns"]
        self.assertIn("CO-WC100", cols)
        self.assertIn("ACI-90WL", cols)
        self.assertEqual([r[cols.index("CO-WC100")] for r in self.tab["rows"]],
                         ["0", "0", "3000"])
        self.assertEqual([r[cols.index("ACI-90WL")] for r in self.tab["rows"]],
                         ["0", "0", "0"])

    def test_an_empty_column_is_dropped_and_a_wordless_one_is_not(self):
        """Of the 70 printed letters this fixture fills 8. A column with
        neither a heading nor a value is furniture; one with values and no
        heading is data, and is named for its letter."""
        self.assertEqual(len(self.tab["columns"]), 9)
        self.assertNotIn("Column CC", self.tab["columns"])

    def test_without_the_borders_the_heading_still_reads(self):
        """A sheet that draws no cell borders falls back to the gap between
        wrapped lines: 1.4pt inside the heading, 4.4pt to the row above."""
        tab = og.parse_page(_Page(rules=[]))
        self.assertEqual([r[0] for r in tab["rows"]], ["1", "2", "3"])
        self.assertIn("Bridge Plug Set Depth (m)", tab["columns"])


class WhatIsNotTheSheet(unittest.TestCase):
    """detect_page takes three independent things to say yes. #705 is what
    one substring on its own was worth: canyon_tables matched a bare
    "Treatment Summary" and claimed 44 pages of Peloton section bars."""

    def test_the_sheet_is_claimed(self):
        self.assertTrue(og.detect_page(_Page()))
        self.assertEqual(og.find_summary_pages(_Doc([_Page()])),
                         [{"kind": "datacapture", "title": og.TITLE,
                           "pages": [1]}])

    def test_the_words_treatment_report_are_not_enough(self):
        page = _Page(text="Halliburton\nTreatment Report\nTreatment Summary\n")
        self.assertFalse(og.detect_page(page))

    def test_the_stamp_alone_is_not_enough(self):
        """A workbook's instructions tab carries the stamp and no grid."""
        page = _Page(text=STAMP + "\nInstructions\nPull Data From TR\n")
        self.assertFalse(og.detect_page(page))

    def test_the_headings_alone_are_not_enough(self):
        self.assertFalse(og.detect_page(_Page(text=LABELS)))

    def test_a_sheet_printed_without_its_column_letters_is_not_claimed(self):
        """Everything here is built on the printed letter strip. Without it
        there is no column model, so there is nothing to claim."""
        self.assertFalse(og.detect_page(_Page(letters=LETTERS[:6])))

    def test_a_run_of_capitals_is_not_a_column_strip(self):
        """The letters have to run in Excel's own order."""
        muddled = [(l, cx) for l, cx in reversed(LETTERS)]
        muddled = [(l, LETTERS[i][1]) for i, (l, _c) in enumerate(muddled)]
        self.assertFalse(og.detect_page(_Page(letters=muddled)))


class ItIsWiredIn(unittest.TestCase):
    """A parser nothing calls is a parser the client never sees. Half the
    table modules in this repo were built, verified and left unreachable
    until 01155's Totals page turned up parsing cleanly into 22 rows that
    had never once been exported."""

    def test_the_pipeline_imports_it(self):
        import pipeline
        self.assertIs(pipeline.ogc_datacapture, og)

    def test_the_pipeline_asks_for_it(self):
        import pipeline
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "pipeline.py")).read()
        self.assertIn("ogc_datacapture.parse_document(doc)", src)
        self.assertIn("ogc_datacapture.parse_job_summary(doc)", src)
        self.assertIn("ogc_datacapture.detect(doc)", src)

    def test_both_tables_classify_as_summaries(self):
        """Titled only "Frac Fluid and Additive Treatment Report" they land
        in table_kind's "other" and the Lab has nowhere to file them."""
        import pipeline
        self.assertEqual(pipeline.table_kind(og.TABLE_TITLE), "summary")
        self.assertEqual(pipeline.table_kind(og.JOB_TITLE), "summary")


DRIVE = "/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023"
F00915 = glob.glob(f"{DRIVE}/00915-102051208015W600_40229_COMP_2022JUN02.pdf")


@unittest.skipUnless(F00915, "the BCER drive is not mounted")
class TheRealPage(unittest.TestCase):
    """Read off 00915 p103 itself, against what the page prints."""

    @classmethod
    def setUpClass(cls):
        cls.doc = fitz.open(F00915[0])
        cls.tab = og.parse_document(cls.doc)

    def test_the_document_is_claimed_on_one_page_of_151(self):
        self.assertTrue(og.detect(self.doc))
        self.assertEqual(og.find_summary_pages(self.doc),
                         [{"kind": "datacapture", "title": og.TITLE,
                           "pages": [103]}])

    def test_twenty_three_stages(self):
        self.assertEqual([r[0] for r in self.tab["rows"]],
                         [str(n) for n in range(1, 24)])
        self.assertEqual(len(self.tab["columns"]), 67)

    def test_stage_1_as_the_page_prints_it(self):
        row = dict(zip(self.tab["columns"], self.tab["rows"][0]))
        self.assertEqual(row["Stage Description"], "Toe")
        self.assertEqual(row["Start Date"], "23-Apr-22")
        self.assertEqual(row["Start Time"], "9:48")
        self.assertEqual(row["End Time"], "10:58")
        self.assertEqual(row["Job Duration"], "70")
        self.assertEqual(row["Hole Vol (m3)"], "39.72")
        self.assertEqual(row["Interval Bottom (m)"], "5368.17")
        self.assertEqual(row["Interval Top (m)"], "5368.07")
        self.assertEqual(row["Bridge Plug Set Depth (m)"], "5369.17")
        self.assertEqual(row["Perforation Intervals (m)"],
                         "5368.17 - 5368.07")
        self.assertEqual(row["Breakdown Press (MPa)"], "39.1")
        self.assertEqual(row["Avg. Press (MPa)"], "62.6")
        self.assertEqual(row["Max. Press (MPa)"], "64.5")
        self.assertEqual(row["ISIP (MPa)"], "19.1")
        self.assertEqual(row["Frac Gradient (kPa/m)"], "19706.3")
        self.assertEqual(row["Avg. Rate (m3/min)"], "7.99")
        self.assertEqual(row["Max. Rate (m3/min)"], "8.74")
        self.assertEqual(row["Fluid Type"], "Slickwater")
        self.assertEqual(row["Slickwater"], "445")
        self.assertEqual(row["H015"], "4")
        self.assertEqual(row["Total Clean Fluid (m3)"], "448.7")
        self.assertEqual(row["Total Injected (m3)"], "474.8")
        self.assertEqual(row["Fluid Salinity (%)"], "18.6%")
        self.assertEqual(row["Acid 15%HCl (m3)"], "4.0")
        self.assertEqual(row["Max Prop Conc (KgPA)"], "375")
        self.assertEqual(row["UWI"], "102/05-12-080-15W6/00")
        self.assertEqual(row["Base Fluid"], "Saline Water")
        self.assertEqual(row["Acid Type"], "HCL")

    def test_the_blank_cells_of_stage_1_are_blank(self):
        """Three cells on that row print nothing, and each of them sits
        between two that do. They are where an off-by-one would show."""
        row = dict(zip(self.tab["columns"], self.tab["rows"][0]))
        self.assertEqual(row["Pre-Job ISIP (MPa)"], "")
        self.assertEqual(row["Fresh Water"], "")
        self.assertEqual(row["Fluid Temperature (degC)"], "")

    def test_stage_2_as_the_page_prints_it(self):
        row = dict(zip(self.tab["columns"], self.tab["rows"][1]))
        self.assertEqual(row["Stage Description"], "PnP")
        self.assertEqual(row["Start Date"], "23-Apr-22")
        self.assertEqual(row["Start Time"], "23:31")
        self.assertEqual(row["End Date"], "24-Apr-22")
        self.assertEqual(row["End Time"], "1:25")
        self.assertEqual(row["Job Duration"], "114")
        self.assertEqual(row["Interval Bottom (m)"], "5350.37")
        self.assertEqual(row["Interval Top (m)"], "5242.07")
        self.assertEqual(row["Total Clean Fluid (m3)"], "881.2")
        self.assertEqual(row["Pumped Total (kg)"], "231,000")
        self.assertEqual(row["BALL SEAT PRESSURE"], "22.8")
        self.assertEqual(row["ACID PRESSURE DROP"], "10.0")
        self.assertEqual(row["WORK (MWt*Hr)"], "55.7")

    def test_stage_19_is_the_row_that_proves_the_proppant_columns(self):
        """The one stage that misses design: 10,000 kg pumped against
        231,000 designed, and the sheet's own Difference cell says 221,000.
        Off by one column and that arithmetic stops working."""
        row = dict(zip(self.tab["columns"], self.tab["rows"][18]))
        self.assertEqual(row["Stage"], "19")
        self.assertEqual(row["Placed (kg)"], "10,000")
        self.assertEqual(row["Pumped (kg)"], "10,000")
        self.assertEqual(row["Placed Total (kg)"], "10,000")
        self.assertEqual(row["Pumped Total (kg)"], "10,000")
        self.assertEqual(row["Designed Sand (kg)"], "231,000")
        self.assertEqual(row["Difference (kg)"], "221,000")
        placed = float(row["Pumped Total (kg)"].replace(",", ""))
        design = float(row["Designed Sand (kg)"].replace(",", ""))
        self.assertEqual(design - placed,
                         float(row["Difference (kg)"].replace(",", "")))

    def test_stage_23_is_the_last_row_and_its_difference_is_blank(self):
        row = dict(zip(self.tab["columns"], self.tab["rows"][22]))
        self.assertEqual(row["Stage"], "23")
        self.assertEqual(row["Start Date"], "9-May-22")
        self.assertEqual(row["End Time"], "8:12")
        self.assertEqual(row["Interval Bottom (m)"], "2704.37")
        self.assertEqual(row["Interval Top (m)"], "2542.07")
        self.assertEqual(row["Designed Sand (kg)"], "330,000")
        self.assertEqual(row["Difference (kg)"], "")
        self.assertEqual(row["Base Fluid"], "Fresh Water")
        self.assertEqual(row["Fresh Water"], "716")

    def test_the_thirteen_named_additives_are_thirteen_columns(self):
        for name in ("CO-WC100", "ACI-90WL", "F114", "H028", "U106",
                     "SFT-NE6D", "A264A", "XE363", "SCI-B702", "BLE-475U",
                     "Soda Ash", "DFR-B665"):
            self.assertIn(name, self.tab["columns"])

    def test_the_job_header_above_the_grid(self):
        job = og.parse_job_summary(self.doc)
        self.assertEqual(_named(job, "Service Company"),
                         "Liberty Oilfield Services")
        self.assertEqual(_named(job, "Company"), "ARC RESOURCES LTD.")
        self.assertEqual(_named(job, "Well License"), "40229")
        self.assertEqual(_named(job, "Formation"), "UMA")
        self.assertEqual(_named(job, "Total Volume"), "14521.0")
        self.assertEqual(_named(job, "Total Proppant"), "5,026,000")
        self.assertEqual(_named(job, "Total Pump Time"), "1871")
        self.assertEqual(_named(job, "Max Rate"), "13.66")

    def test_every_row_agrees_with_its_own_clock(self):
        """End minus Start is Job Duration on all 23 rows. Five columns
        have to be right for that to hold, and any shift breaks it."""
        self.assertEqual(_clock_mismatches(self.tab), [])

    def test_the_page_really_is_turned_and_really_has_text(self):
        """Stated so the tests above cannot pass for the wrong reason."""
        page = self.doc[102]
        self.assertEqual(page.rotation, 90)
        self.assertEqual(len(page.get_text("words")), 1855)
        self.assertEqual(len(page.get_text()), 9930)


F00919 = glob.glob(f"{DRIVE}/__LIB/00919-105011108015W600_40233_COMP_2022JUN06"
                   f".pdf")


@unittest.skipUnless(F00919, "the BCER drive is not mounted")
class TheSameSheetPrintedUPRIGHT(unittest.TestCase):
    """00919 p108 is the same workbook on a well next door, and its page is
    NOT turned — /Rotate 0, 1411 words, 7701 characters. Nothing here may
    assume the sideways case: the rotation matrix of an unrotated page is
    the identity and the same code has to read both. 17 stages, and only 62
    of the 70 columns are printed at all on this revision of the sheet."""

    @classmethod
    def setUpClass(cls):
        cls.doc = fitz.open(F00919[0])
        cls.tab = og.parse_document(cls.doc)

    def test_the_upright_sheet_reads(self):
        self.assertEqual(self.doc[107].rotation, 0)
        self.assertEqual(og._pages(self.doc), [107])
        self.assertEqual([r[0] for r in self.tab["rows"]],
                         [str(n) for n in range(1, 18)])
        self.assertEqual(len(self.tab["columns"]), 62)

    def test_stage_1_as_the_page_prints_it(self):
        row = dict(zip(self.tab["columns"], self.tab["rows"][0]))
        self.assertEqual(row["Stage Description"], "Toe")
        self.assertEqual(row["Start Time"], "5:30")
        self.assertEqual(row["End Time"], "6:30")
        self.assertEqual(row["Job Duration"], "60")
        self.assertEqual(row["Hole Vol (m3)"], "36.85")
        self.assertEqual(row["Interval Bottom (m)"], "4979.33")
        self.assertEqual(row["Interval Top (m)"], "4979.23")
        self.assertEqual(row["Bridge Plug Set Depth (m)"], "4980.33")
        self.assertEqual(row["Perforation Intervals (m)"],
                         "4979.33 - 4979.23")
        self.assertEqual(row["Avg. Press (MPa)"], "60.9")
        self.assertEqual(row["ISIP (MPa)"], "19.8")
        self.assertEqual(row["Avg. Rate (m3/min)"], "9.52")
        self.assertEqual(row["Total Clean Fluid (m3)"], "472.1")
        self.assertEqual(row["Total Injected (m3)"], "498.1")
        self.assertEqual(row["Designed Sand (kg)"], "66,000")
        self.assertEqual(row["UWI"], "105/01-11-080-15W6/00")

    def test_every_row_agrees_with_its_own_clock(self):
        self.assertEqual(_clock_mismatches(self.tab), [])

    def test_the_job_header_is_the_neighbouring_well(self):
        job = og.parse_job_summary(self.doc)
        self.assertEqual(_named(job, "Well Name"),
                         "ARCRES HZ DOE F16-15-080-15")
        self.assertEqual(_named(job, "Well License"), "40233")
        self.assertEqual(_named(job, "Total Proppant"), "5,379,000")


if __name__ == "__main__":
    unittest.main()
