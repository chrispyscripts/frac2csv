"""The notes a printout's reading gives the export (mudlog_pdf_app._notes):
its lines of text put back together into the log's notes.

Lines made up in the test, never a client's.

Run: python3 -m unittest tests.test_mudlog_notes
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import fitz  # noqa: F401  (mudlog_pdf_app reads PDFs with it)
except ImportError:          # pragma: no cover
    fitz = None

if fitz:
    import mudlog_pdf_app as A

TRACKS = [{"title": "Curves", "keys": ["curves"], "x0": 0.0, "x1": 200.0},
          {"title": "MD", "keys": ["depth"], "x0": 200.0, "x1": 210.0},
          {"title": "Descriptions", "keys": ["descriptions"], "x0": 210.0, "x1": 600.0}]
CURVES = [{"name": "ROP", "unit": "min/m"}]


def line(depth, a0, a1, height, text):
    return {"depth": depth, "across": [a0, a1], "height": height, "text": text}


@unittest.skipUnless(fitz, "PyMuPDF not installed")
class DownThePage(unittest.TestCase):
    """a log printed with depth down the page: a line runs across the strip"""

    def notes(self, text):
        return A._notes(text, TRACKS, {"pt_per_m": 11.8, "depth_on_page": "down"}, CURVES)

    def test_lines_with_no_gap_are_one_note_and_a_gap_starts_the_next(self):
        got = self.notes([
            line(1000.0, 220, 580, 0.8, "1000-1005 SS: lt gy, vf gr,"),
            line(1000.8, 220, 500, 0.8, "w srt, calc cmt,"),
            line(1001.6, 220, 300, 0.8, "tr pyr."),
            line(1003.0, 220, 580, 0.8, "1005-1010 SH: m gy, sbfis."),
        ])
        self.assertEqual([(n["depth"], n["column"], n["text"]) for n in got], [
            (1000.0, "Descriptions", "1000-1005 SS: lt gy, vf gr, w srt, calc cmt, tr pyr."),
            (1003.0, "Descriptions", "1005-1010 SH: m gy, sbfis.")])

    def test_type_of_another_size_straight_after_is_another_note(self):
        got = self.notes([
            line(1000.0, 220, 400, 1.1, "Top Marker:"),
            line(1001.1, 220, 500, 1.1, "1001.0 m MD, 990.5 m TVD"),
            line(1002.3, 220, 580, 0.85, "1000-1005 SS: lt gy, vf gr"),
        ])
        self.assertEqual([n["text"] for n in got], ["Top Marker: 1001.0 m MD, 990.5 m TVD",
                                                     "1000-1005 SS: lt gy, vf gr"])

    def test_notes_side_by_side_in_one_column_are_apart(self):
        got = self.notes([
            line(1000.0, 20, 80, 0.67, "Bit No: 2"),
            line(1000.0, 120, 140, 0.67, "HS"),
            line(1000.67, 20, 90, 0.67, "Size: 222 mm"),
        ])
        self.assertEqual(sorted(n["text"] for n in got), ["Bit No: 2 Size: 222 mm", "HS"])
        self.assertEqual({n["column"] for n in got}, {"Curves"})

    def test_one_blank_line_is_inside_a_note(self):
        got = self.notes([
            line(1004.0, 20, 60, 0.67, "Den 1080"),
            line(1004.67, 20, 60, 0.67, "Vis 45"),
            line(1006.01, 20, 60, 0.67, "pH 9.0"),
        ])
        self.assertEqual([n["text"] for n in got], ["Den 1080 Vis 45 pH 9.0"])

    def test_a_samples_description_after_a_blank_line_is_its_own_note(self):
        got = self.notes([
            line(1250.0, 410, 600, 0.85, "1250-1255 LS: lt beige, micxl,"),
            line(1250.85, 410, 450, 0.85, "no show."),
            line(1252.55, 410, 600, 0.85, "1255-1257.6 SILTY LS: buff,"),
        ])
        self.assertEqual([n["text"] for n in got], ["1250-1255 LS: lt beige, micxl, no show.",
                                                     "1255-1257.6 SILTY LS: buff,"])

    def test_captions_scales_and_depth_labels_are_not_notes_but_a_toolface_is(self):
        got = self.notes([
            line(1010.0, 60, 100, 0.67, "ROP (min/m)"),
            line(1010.0, 2, 6, 0.67, "0"),
            line(1010.0, 190, 198, 0.67, "10"),
            line(1010.67, 50, 110, 0.67, "Pason Gas (units)"),
            line(1010.67, 190, 198, 0.67, "500"),
            line(1009.3, 201, 209, 1.4, "1010"),
            line(1003.0, 120, 135, 0.67, "180"),
        ])
        self.assertEqual([(n["depth"], n["text"]) for n in got], [(1003.0, "180")])


@unittest.skipUnless(fitz, "PyMuPDF not installed")
class AlongTheStrip(unittest.TestCase):
    """a lateral printed with depth across the page: a line runs along the
    depth and a note's lines stack across the strip, its first at the high
    edge"""

    def notes(self, text):
        return A._notes(text, TRACKS, {"pt_per_m": 11.8, "depth_on_page": "across"}, CURVES)

    def test_a_notes_lines_stack_across_from_the_high_edge(self):
        got = self.notes([
            line(2000.0, 330, 340, 5.0, "tr pyr."),
            line(2000.0, 350, 360, 15.0, "2000-2020 SS: lt gy, vf gr, w srt,"),
            line(2000.0, 340, 350, 14.0, "calc cmt, p intgran por,"),
            line(2030.0, 350, 360, 12.0, "2020-2040 SH: m gy, sbfis."),
        ])
        self.assertEqual([(n["depth"], n["text"]) for n in got], [
            (2000.0, "2000-2020 SS: lt gy, vf gr, w srt, calc cmt, p intgran por, tr pyr."),
            (2030.0, "2020-2040 SH: m gy, sbfis.")])

    def test_a_line_cut_by_a_page_join_is_put_back_together(self):
        first = "2000-2020 SS: lt gy, f gr, intgr"           # 32 letters over 9 m
        got = self.notes([
            line(2000.0, 350, 360, 9.0, first),
            line(2008.7, 350, 360, 6.0, "ran por, w srt, calc"),   # the "r" the join cut, on both pages
            line(2000.0, 340, 350, 9.0, "dolic cmt, fr intgran por,"),
            line(2008.98, 340, 350, 4.0, "calc cmt."),          # a join at a space: "por" and "calc" are words
        ])
        self.assertEqual([n["text"] for n in got], [
            "2000-2020 SS: lt gy, f gr, intgran por, w srt, calc dolic cmt, fr intgran por, calc cmt."])


if __name__ == "__main__":
    unittest.main()
