"""The IFS legend's axis letter, read off the glyph the page draws (#699, #711).

  python3 -m unittest tests.test_ifs_legend_letter

00973 (Crew, Halliburton IFS v7) has no text layer on any chart page, so the
legend is rebuilt from OCR. A "Chemical Additives" page prints its six axis
letters in a column of their own, one character each, in the series' colours
— p108 draws "A B A A B A" at page (93..191, 120..131) — and the whole-page
OCR pass at 200 dpi returns NONE of them, while every name word on the same
rows reads at confidence 89-96. Every entry lost its letter, an entry with
no letter is dropped, and the page raised "IFS: legend not found".

Measured on 00973 with the drive mounted: 184 pages pass detect(), 59 of
them raised "legend not found" before this change and 34 after. The 25
recovered are all 24 "Chemical Additives" pages and one real treatment
chart, p187, whose two-column legend lost the letters of its left column.
No page that extracted before stopped, and no page that extracted both ways
changed a single value.

The sister filing 00971 moves the same way: 181 detected, 61 "legend not
found" before and 32 after, 29 recovered (25 Chemical Additives, 3 treatment
charts, 1 whose title OCR lost), again with nothing broken. Exactly one
page in the two files has its NUMBERS changed by this, 00971 p120, and it
changed because the old answer was wrong — see WhereTheUnitRuleWasWrong.

The pages still failing are the "Offset Wells" pages — 34 in 00973, 32 in
00971 — which print ONE ladder and no axis letter anywhere on the sheet
(00973 p109, p114, p119, p124 and 30 more). There is nothing on those pages
to read, and inventing a letter for them is the guess that put Slurry Rate
on the concentration axis in #709. They are left failing.

The letter is READ, never inferred: the crop holds one glyph and must come
back as one A-F character, and a row with more than one unread glyph of its
own colour is refused rather than picked from.
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz                                                # noqa: E402

import halliburton_ifs as ifs                              # noqa: E402
import ocr_labels                                          # noqa: E402


class _Page(object):
    """Just enough page for _outline_colours: coloured filled rectangles."""

    def __init__(self, fills):
        self._f = fills

    def get_drawings(self):
        out = []
        for rgb, rect in self._f:
            c = (((rgb >> 16) & 255) / 255.0, ((rgb >> 8) & 255) / 255.0,
                 (rgb & 255) / 255.0)
            out.append({"type": "f", "fill": c, "rect": fitz.Rect(*rect),
                        "items": []})
        return out


class _Reads(object):
    """ocr_labels stubbed: what the page OCR covered, and what a crop says."""

    def __init__(self, covered=(), texts=()):
        self.covered, self.texts = list(covered), list(texts)
        self.asked = []

    def __enter__(self):
        self._save = (ocr_labels.available, ocr_labels.words,
                      ocr_labels.span_texts)
        ocr_labels.available = lambda: True
        ocr_labels.words = lambda page, **k: [
            {"rect": fitz.Rect(*r)} for r in self.covered]

        def span_texts(page, spans):
            self.asked = [tuple(b) for b, _d in spans]
            return list(self.texts)[:len(spans)]

        ocr_labels.span_texts = span_texts
        return self

    def __exit__(self, *exc):
        (ocr_labels.available, ocr_labels.words,
         ocr_labels.span_texts) = self._save
        return False


# 00973 p108's own geometry. The page is a rotated build, so a row's (cx, cy)
# are _unrotate'd centres while the glyph rects below are raw page boxes.
ROWS = [
    {"t": "EC-1 Conc (L/m3)", "color": 0xFF0000, "cx": -658.6, "cy": 116.3},
    {"t": "MX 2-2822 Conc (L/m3)", "color": 0x00FF00, "cx": -663.8,
     "cy": 133.7},
]
GLYPHS = [(0xFF0000, (110.88, 120.96, 121.80, 130.08)),
          (0x00FF00, (128.28, 120.00, 139.20, 131.28))]
# the colour rule the legend draws on the same row, between name and letter
SWATCH = (0x00FF00, (98.28, 113.88, 98.28, 275.28))


class GlyphLetters(unittest.TestCase):

    def test_the_letters_ocr_never_returned_are_read(self):
        with _Reads(texts=["B", "A"]) as r:
            got = ifs._glyph_letters(_Page(GLYPHS), ROWS, True)
        self.assertEqual(got, {0: "B", 1: "A"})
        # and each was read from its own glyph box, not the row's
        self.assertEqual(r.asked, [g[1] for g in GLYPHS])

    def test_the_swatch_rule_is_not_a_glyph(self):
        # 161pt of colour on the row; the letter beside it is 11
        with _Reads(texts=["A"]):
            got = ifs._glyph_letters(_Page([SWATCH]), ROWS, True)
        self.assertEqual(got, {})

    def test_a_glyph_the_page_ocr_already_read_is_not_the_letter(self):
        # the name's OWN letters are glyphs too, in the same ink on the same
        # row: "Optikleen-WF Conc (kg/m3)" is 20 of them on 00973 p108
        with _Reads(covered=[(128.0, 119.5, 140.0, 132.0)], texts=["B", "A"]):
            got = ifs._glyph_letters(_Page(GLYPHS), ROWS, True)
        self.assertEqual(got, {0: "B"})       # not {0: "B", 1: "A"}

    def test_two_unread_glyphs_on_a_row_are_refused(self):
        # a second red glyph further along the SAME row (raw y moves, which
        # is the row's own direction on a rotated page)
        extra = (0xFF0000, (110.88, 140.00, 121.80, 149.00))
        with _Reads(texts=["A"]):
            got = ifs._glyph_letters(_Page(GLYPHS + [extra]), ROWS, True)
        self.assertEqual(got, {1: "A"})

    def test_the_same_glyph_drawn_twice_is_one_glyph(self):
        # 00973 p203 overprints its artwork: every legend letter is drawn
        # twice at bit-identical coordinates, and 541 of its 1163 filled
        # paths are exact duplicates
        twice = [GLYPHS[0], GLYPHS[0], GLYPHS[1], GLYPHS[1]]
        with _Reads(texts=["B", "A"]):
            got = ifs._glyph_letters(_Page(twice), ROWS, True)
        self.assertEqual(got, {0: "B", 1: "A"})

    def test_a_crop_that_does_not_read_as_one_letter_is_refused(self):
        for bad in ("", "Cc", "AB", "8", "Conc"):
            with _Reads(texts=[bad, "A"]):
                got = ifs._glyph_letters(_Page(GLYPHS), ROWS, True)
            self.assertEqual(got, {1: "A"}, bad)

    def test_a_letter_of_another_colour_is_not_adopted(self):
        # a rate letter cannot stand in for a concentration's
        mismatched = [(0x0000FF, GLYPHS[0][1]), (0x0000FF, GLYPHS[1][1])]
        with _Reads(texts=["B", "A"]):
            got = ifs._glyph_letters(_Page(mismatched), ROWS, True)
        self.assertEqual(got, {})

    def test_a_black_row_is_left_alone(self):
        # black is the frame, the grid, the ticks and the tick digits; an
        # unread black glyph on a row is as likely to be a tick mark
        black_row = [dict(ROWS[0], color=0)]
        with _Reads(texts=["A"]):
            got = ifs._glyph_letters(_Page([(0x000000, GLYPHS[0][1])]),
                                     black_row, True)
        self.assertEqual(got, {})

    def test_a_glyph_on_another_row_is_not_adopted(self):
        # raw x is the row coordinate on a rotated page: ~100pt clear of it
        below = [(0xFF0000, (210.88, 120.96, 221.80, 130.08))]
        with _Reads(texts=["B"]):
            got = ifs._glyph_letters(_Page(below), ROWS, True)
        self.assertEqual(got, {})


class LegendUsesIt(unittest.TestCase):
    """_legend hands the rows over and keeps what comes back."""

    def spans(self):
        # one OCR'd legend row, split into words the way 00973 p108 reads
        return [
            {"t": "EC-1", "color": 0xFF0000, "cx": -658.6, "cy": 116.3,
             "ocr": True},
            {"t": "Conc", "color": 0xFF0000, "cx": -613.1, "cy": 116.3,
             "ocr": True},
            {"t": "(L/m?)", "color": 0xFF0000, "cx": -565.7, "cy": 117.7,
             "ocr": True},
        ]

    def test_without_the_page_the_row_is_still_dropped(self):
        self.assertEqual(ifs._legend(self.spans()), [])

    def test_with_the_page_the_row_keeps_its_axis(self):
        with _Reads(texts=["B"]):
            got = ifs._legend(self.spans(), _Page(GLYPHS[:1]), True)
        self.assertEqual(got, [("EC-1 Conc", "L/m?", 0xFF0000, "B")])


DRIVE = glob.glob("/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/"
                  "00973-100131208122W602_41210_COMP_2021SEP24.pdf")


@unittest.skipUnless(DRIVE and ocr_labels.available(),
                     "the BC drive or tesseract is not here")
class OnThePage(unittest.TestCase):

    def test_00973_p108_reads_the_five_letters_it_can(self):
        # the page draws A B A A B A; the first is the black LXD row, which
        # an OCR'd page cannot separate from the axes' own ink and which this
        # reader has never claimed
        doc = fitz.open(DRIVE[0])
        page = doc[107]
        rotated = ifs.page_rotated(page)
        legend = ifs._legend(ifs._spans(page, rotated), page, rotated)
        self.assertEqual(sorted((n.split()[0], ax) for n, _u, _c, ax in legend),
                         sorted([("EC-1", "B"), ("MX", "A"), ("MC", "A"),
                                 ("PCCS-101", "B"), ("Optikleen-WF", "A")]))
        ifs.extract_page(page)           # no longer "IFS: legend not found"

    def test_00973_p109_has_no_letter_to_read_and_stays_unread(self):
        # "Interval 1 - Offset Wells": one ladder, four series, and not one
        # axis letter anywhere on the sheet. Nothing to read is not a licence
        # to guess.
        doc = fitz.open(DRIVE[0])
        with self.assertRaises(ValueError) as e:
            ifs.extract_page(doc[108])
        self.assertIn("legend not found", str(e.exception))


DRIVE71 = glob.glob("/Volumes/CnC-2TB-ssd/BCER-Frac/Spud-2019-2023/"
                    "00971-102041308122W600_41208_COMP_2021SEP23.pdf")


@unittest.skipUnless(DRIVE71 and ocr_labels.available(),
                     "the BC drive or tesseract is not here")
class WhereTheUnitRuleWasWrong(unittest.TestCase):
    """The page's own letter beats reasoning from the unit (_adopt_orphans).

    00971 p120 is the only page in either file whose numbers this change
    moves, and it moves them because the old answer was wrong. Its legend has
    two columns; OCR read the left one's letters and none of the right one's,
    so EC-1 Conc (L/m3) and MC B-8510 Conc (L/m3) were adopted onto axis A —
    the axis MX 2-2822 Conc (L/m3) had — by the rule that one unit means one
    ladder. The page prints B beside both of them, in their own ink, and
    reading it takes EC-1 from 0..3.00 down to 0..0.60 and MC from 2.77 to
    0.55, exactly the 5x between the two ladders. Optikleen-WF, dropped
    before for want of a letter, comes back on A.

    (What the page does NOT settle: p120 heads TWO of its three ladders "B",
    0..0.6 and 0..2.0. The reader takes the first, which is the one the
    already-lettered PCCS-101 row uses. That ambiguity is the document's and
    belongs to whoever owns the letter-to-column mapping; it is on none of
    the 54 pages this change recovers.)
    """

    def legend(self, with_page):
        doc = fitz.open(DRIVE71[0])
        page = doc[119]
        rotated = ifs.page_rotated(page)
        spans = ifs._spans(page, rotated)
        out = (ifs._legend(spans, page, rotated) if with_page
               else ifs._legend(spans))
        return {n.split()[0]: ax for n, _u, _c, ax in out}

    def test_the_unit_rule_puts_the_right_hand_column_on_A(self):
        was = self.legend(False)
        self.assertEqual(was.get("EC-1"), "A")
        self.assertEqual(was.get("MC"), "A")
        self.assertIsNone(was.get("Optikleen-WF"))

    def test_the_page_says_B_and_the_page_wins(self):
        now = self.legend(True)
        self.assertEqual(now["EC-1"], "B")
        self.assertEqual(now["MC"], "B")
        self.assertEqual(now["Optikleen-WF"], "A")
        # the rows whose letters OCR did read are untouched
        self.assertEqual(now["MX"], "A")
        self.assertEqual(now["|PCCS-101"], "B")


if __name__ == "__main__":
    unittest.main()
