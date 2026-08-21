"""Rebuilding a legend entry from OCR'd words.

  python3 -m unittest tests.test_legend_row

A Liberty legend entry is one line of words in one ink: "475 CONC (kg/m3)".
OCR hands them back separately, so they are regrouped by colour and read
along the line. Two things go wrong and both change the NAME:

  * a stray mark in the same ink — OCR turns a stroke of chart ink into "|"
    three hundred points below the legend — joins the group and makes the
    vertical spread the larger one, so the words get read DOWN the page. On a
    row they all share a coordinate, so that is a tie, and the name comes out
    in whatever order the spans happened to arrive: "CONC 475" on 28 pages of
    00913, and a bare "CONC" where the code word is lost with it.

  * the fix for it, if the reading direction is decided inside the sort key.
    `items` IS `row` there, and CPython empties a list while list.sort() runs
    so mutation during the sort is caught — so len(row) is 0 inside the key,
    the else branch wins, and it sorts by the wrong coordinate anyway. The
    last test is that trap.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1


def w(t, cx, cy, color=0xFF0000):
    return {"t": t, "cx": cx, "cy": cy, "color": color, "ocr": True}


def names(out):
    return sorted(s["t"] for s in out)


class LegendRow(unittest.TestCase):
    def test_a_plain_row_reads_left_to_right(self):
        out = lib1._ocr_legend_spans([
            w("475", 164.2, 126.5), w("CONC", 205.4, 126.4),
            w("(kg/m?)", 253.6, 127.8)])
        self.assertEqual(names(out), ["475 CONC (kg/m3)"])

    def test_the_00913_stray_mark_does_not_reverse_the_name(self):
        # the '|' is 320 points below the row, in the same ink
        out = lib1._ocr_legend_spans([
            w("475", 164.2, 126.5), w("CONC", 205.4, 126.4),
            w("(kg/m?)", 253.6, 127.8), w("|", 375.7, 450.0)])
        self.assertEqual(names(out), ["475 CONC (kg/m3)"])

    def test_the_stray_mark_is_not_taken_into_the_name(self):
        out = lib1._ocr_legend_spans([
            w("AQUGAR", 501.7, 114.3), w("CONC", 558.5, 114.1),
            w("{", 586.1, 117.7), w("L/m?)", 605.7, 115.6),
            w("|", 400.0, 460.0)])
        self.assertEqual(names(out), ["AQUGAR CONC (L/m3)"])

    def test_a_column_legend_reads_top_to_bottom(self):
        # a rotated sheet stacks the words instead of lining them up
        out = lib1._ocr_legend_spans([
            w("475", 100.0, 200.0), w("CONC", 100.4, 214.0),
            w("(kg/m?)", 99.6, 228.0)])
        self.assertEqual(names(out), ["475 CONC (kg/m3)"])

    def test_two_colours_are_two_entries(self):
        out = lib1._ocr_legend_spans([
            w("475", 164.2, 126.5), w("CONC", 205.4, 126.4),
            w("(kg/m?)", 253.6, 127.8),
            w("B702", 487.6, 126.4, 0xFF8000),
            w("CONC", 529.6, 126.4, 0xFF8000),
            w("(Lim", 569.3, 127.8, 0xFF8000)])
        self.assertEqual(names(out), ["475 CONC (kg/m3)", "B702 CONC (L/m3)"])

    def test_a_unit_first_entry_is_refused_rather_than_named_wrongly(self):
        # cut == 0 means the bracket led; there is no name to take
        out = lib1._ocr_legend_spans([
            w("(kg/m?)", 100.0, 126.4), w("CONC", 150.0, 126.4)])
        self.assertEqual(out, [])

    def test_one_word_is_not_an_entry(self):
        self.assertEqual(lib1._ocr_legend_spans([w("CONC", 205.4, 126.4)]), [])

    def test_black_words_are_not_legend_entries(self):
        out = lib1._ocr_legend_spans([
            w("475", 164.2, 126.5, 0), w("CONC", 205.4, 126.4, 0),
            w("(kg/m?)", 253.6, 127.8, 0)])
        self.assertEqual(out, [])

    def test_a_long_row_still_reads_along_the_row(self):
        # THE SORT-KEY TRAP. With five words on a row and one stray, a key
        # that asks len(row) sees 0 mid-sort and reads down the page instead;
        # every word shares cy, the sort ties, and the name comes back in
        # arrival order. Arrival order here is deliberately reversed.
        out = lib1._ocr_legend_spans([
            w("(kg/m?)", 300.0, 126.0), w("CONC", 250.0, 126.1),
            w("PROP", 200.0, 126.0), w("BTM", 150.0, 126.1),
            w("|", 400.0, 470.0)])
        self.assertEqual(names(out), ["BTM PROP CONC (kg/m3)"])


if __name__ == "__main__":
    unittest.main()
