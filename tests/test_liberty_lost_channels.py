"""The two ways 00918/00919 lost a channel that is plainly on the sheet.

  python3 -m unittest tests.test_liberty_lost_channels

Carmine reported "missing prop con and slurry rate" on 00918 and 00919
(#707, #708). Both files are Liberty PRC sheets with no usable text layer, so
every label comes from OCR, and both charts named in the report came back
with four channels — Treating Pressure, Prop Conc, "H Prop Conc", GORV
Pressure — where the page draws five.

The spans below are the real ones, taken off 00918 p159 (stage 14) and p133
(stage 1) exactly as extract_page sees them: colour-keyed, and already
swapped for a landscape chart, so cx is the VALUE axis and cy the TIME axis.

THE RATE. The blue axis prints 20/16/12/8/4/0 squeezed between the pressure
and GORV axes 6pt away either side, and OCR reads two of them, 16 and 12.
They are 64.98pt apart against a page whose ladders step 65.16, so
extract_page keeps that axis — but _ocr_legend_spans did not know the rule,
so the same two numbers were also collected as WORDS of the blue name.
Worse, p159 welds the "ry" of the blue "Slurry" to the "V" of the magenta
"GORV" printed 14pt below into one box 31.8pt tall whose centre lands BETWEEN
the two rows (cx 132.3, against 119.5/124.2/125.6 for the blue row), and the
fill sampler scores it blue. The median position landed on that one word,
both candidate lines came back holding only it, and the blue entry was
dropped: the rate was traced, had no name, and never reached the CSV.

p133 is the same sheet with all four rate labels read, and is here because it
is what a line rule can break instead — its four ticks outnumber its three
legend words, so a rule that simply counts must not see them.

THE RATE, AGAIN. 00919 prints the same axis 20/16/12/8/4/0 with its 20 hard
against the magenta 75 of the ladder stacked 6pt below, and tesseract loses
the trailing zero on ten of that file's nineteen treatment charts: p129
(stage 12, the other chart in the report) reads [2, 16, 12], p143 reads
[3, 24, 18, 12] off an axis printed 30/24/18/12/6/0. Three labels that turn
around are not an arithmetic ladder and are not a pair, so p129 was dropped;
p143 has four labels, which are accepted without question, so the 3 went into
the fit and took the axis with it.

THE NAME. OCR eats the leading B of "BH Prop Conc" and _snap_name refuses
what is left, on purpose: "H Prop Conc" is one edit from "BH Prop Conc" and
one from "WH Prop Conc", which are different measurements. The page settles
it — the dark-green sibling on the same sheet reads "Prop Conc", so the
light-green one is the bottom-hole curve, and the sheet does print
"BH Prop Conc (kg/m3)". Nothing is decided when the page does not say.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1


def w(t, cx, cy, color):
    return {"t": t, "cx": cx, "cy": cy, "color": color, "ocr": True}


# 00918 p159 — stage 14, the chart in the report. Blue reads two rate labels
# and carries the welded "RV"; light green has lost the B of "BH Prop Conc".
P159 = [
    w('16', 212.58, 80.28, 0x0000FF),
    w('12', 277.56, 80.28, 0x0000FF),
    w('Slur', 124.20, 162.00, 0x0000FF),
    w('RV', 132.30, 183.24, 0x0000FF),
    w('Rate', 119.52, 204.84, 0x0000FF),
    w('(m?/min', 125.64, 249.30, 0x0000FF),
    w('Prop', 113.22, 486.00, 0x008000),
    w('Conc', 111.96, 522.18, 0x008000),
    w('(kg/m?', 113.40, 563.58, 0x008000),
    w('900', 270.90, 717.30, 0x008000),
    w('600', 336.06, 717.30, 0x008000),
    w('300', 399.96, 717.30, 0x008000),
    w('1500', 142.02, 717.66, 0x008000),
    w('1200', 205.92, 717.66, 0x008000),
    w('H', 124.20, 485.46, 0x80FF00),
    w('Prop', 125.46, 510.12, 0x80FF00),
    w('Conc', 124.20, 546.30, 0x80FF00),
    w('(kg/m?)', 125.64, 590.04, 0x80FF00),
    w('900', 283.32, 717.30, 0x80FF00),
    w('600', 348.48, 717.30, 0x80FF00),
    w('300', 413.46, 717.30, 0x80FF00),
    w('1500', 154.26, 717.66, 0x80FF00),
    w('1200', 219.42, 717.66, 0x80FF00),
    w('51', 264.24, 79.20, 0xFF0000),
    w('34', 329.22, 79.92, 0xFF0000),
    w('85', 135.18, 80.10, 0xFF0000),
    w('68', 200.34, 80.10, 0xFF0000),
    w('17', 394.20, 80.46, 0xFF0000),
    w('freating', 118.08, 174.78, 0xFF0000),
    w('Foressure', 118.08, 234.00, 0xFF0000),
    w('(MPa)', 113.58, 284.94, 0xFF0000),
    w('51', 289.98, 79.20, 0xFF00FF),
    w('34', 355.14, 79.92, 0xFF00FF),
    w('85', 161.10, 80.10, 0xFF00FF),
    w('68', 224.82, 80.10, 0xFF00FF),
    w('17', 419.04, 80.46, 0xFF00FF),
    w('GOR', 137.70, 165.42, 0xFF00FF),
    w('Pressure', 137.70, 224.28, 0xFF00FF),
    w('(M', 139.14, 265.32, 0xFF00FF),
    w('a)', 139.14, 289.98, 0xFF00FF),
]

# 00918 p133 — stage 1 of the same filing, which already read correctly.
# Blue prints four rate labels, so it is a ladder by the ordinary rule.
P133 = [
    w('20', 212.40, 79.92, 0x0000FF),
    w('25', 147.42, 80.10, 0x0000FF),
    w('10', 341.10, 80.28, 0x0000FF),
    w('15', 277.20, 80.46, 0x0000FF),
    w('Slurry', 125.46, 167.76, 0x0000FF),
    w('ate', 124.20, 210.78, 0x0000FF),
    w('(m?/min', 124.02, 251.64, 0x0000FF),
    w('Prop', 117.90, 486.00, 0x008000),
    w('Conc', 111.60, 522.18, 0x008000),
    w('(kg/m?', 113.04, 563.58, 0x008000),
    w('900', 270.54, 717.30, 0x008000),
    w('600', 335.52, 717.30, 0x008000),
    w('300', 399.24, 717.30, 0x008000),
    w('1500', 141.84, 717.66, 0x008000),
    w('1200', 205.74, 717.66, 0x008000),
    w('Btm', 124.02, 483.48, 0x00FF00),
    w('Prop', 125.46, 515.88, 0x00FF00),
    w('Conc', 124.02, 551.70, 0x00FF00),
    w('(kg/m?)', 125.46, 595.44, 0x00FF00),
    w('900', 282.96, 717.30, 0x00FF00),
    w('600', 347.76, 717.30, 0x00FF00),
    w('300', 412.74, 717.30, 0x00FF00),
    w('1500', 154.08, 717.66, 0x00FF00),
    w('1200', 219.06, 717.66, 0x00FF00),
    w('60', 199.98, 79.92, 0xFF0000),
    w('45', 263.88, 79.92, 0xFF0000),
    w('30', 328.86, 79.92, 0xFF0000),
    w('75', 135.36, 80.10, 0xFF0000),
    w('15', 393.84, 80.46, 0xFF0000),
    w('Treatin', 111.78, 170.82, 0xFF0000),
    w('Pressure', 115.38, 234.72, 0xFF0000),
    w('(MPa)', 113.04, 287.10, 0xFF0000),
    w('60', 224.64, 79.92, 0xFF00FF),
    w('45', 289.62, 79.92, 0xFF00FF),
    w('30', 354.42, 79.92, 0xFF00FF),
    w('0', 483.30, 79.92, 0xFF00FF),
    w('75', 160.92, 80.10, 0xFF00FF),
    w('15', 418.32, 80.46, 0xFF00FF),
    w('GORV', 137.52, 170.10, 0xFF00FF),
    w('Pressure', 137.70, 224.28, 0xFF00FF),
    w('(MPa', 137.70, 276.66, 0xFF00FF),
]


def legend(spans):
    """colour -> the rebuilt 'NAME (unit)' span text."""
    return {s["color"]: s["t"] for s in lib1._ocr_legend_spans(spans)}


class TheTwoLabelRateAxisIsNotALegendWord(unittest.TestCase):
    def test_the_page_vouches_for_the_pair(self):
        # 16 and 12, 64.98pt apart, against ladders that step 65.16
        self.assertEqual(lib1._pair_ladders(P159), {0x0000FF})

    def test_p133_reads_four_labels_so_no_pair_is_claimed(self):
        self.assertEqual(lib1._pair_ladders(P133), set())

    def test_the_two_tick_labels_stay_out_of_the_blue_name(self):
        got = legend(P159)[0x0000FF]
        self.assertNotIn("16", got)
        self.assertNotIn("12", got)

    def test_p133_s_four_tick_labels_stay_out_of_the_blue_name(self):
        # the ordinary sibling rule already excludes these; the point is that
        # four ticks outnumber three legend words, so a line rule that counts
        # must not be handed them
        self.assertEqual(legend(P133)[0x0000FF], "Slurry ate (m3/min)")


class TheLegendLineIsTheOneWithTheMostWords(unittest.TestCase):
    def test_00918_p159_keeps_its_rate_entry(self):
        self.assertEqual(legend(P159)[0x0000FF], "Slur Rate (m3/min)")

    def test_and_that_name_is_the_rate(self):
        self.assertEqual(lib1._snap_name("Slur Rate"), "Slurry Rate")

    def test_the_welded_word_is_not_taken_into_the_name(self):
        self.assertNotIn("RV", legend(P159)[0x0000FF])

    def test_the_sheet_s_other_four_entries_are_unchanged(self):
        got = legend(P159)
        self.assertEqual(got[0xFF0000], "freating Foressure (MPa)")
        self.assertEqual(got[0x008000], "Prop Conc (kg/m3)")
        self.assertEqual(got[0x80FF00], "H Prop Conc (kg/m3)")
        self.assertEqual(got[0xFF00FF], "GOR Pressure (M a)")

    def test_p133_reads_exactly_as_it_always_did(self):
        self.assertEqual(legend(P133), {
            0xFF0000: "Treatin Pressure (MPa)",
            0x0000FF: "Slurry ate (m3/min)",
            0x008000: "Prop Conc (kg/m3)",
            0x00FF00: "Btm Prop Conc (kg/m3)",
            0xFF00FF: "GORV Pressure (MPa)",
        })


def named(*pairs):
    """[(name, unit)] -> the {colour: entry} dict extract_page builds."""
    return {i + 1: {"name": n, "unit": u, "at": 0.0}
            for i, (n, u) in enumerate(pairs)}


class TheLostLeadingLetter(unittest.TestCase):
    def test_the_wellhead_sibling_names_this_one_bottomhole(self):
        # 00918 p159 and 00919 p111 exactly: the page prints "Prop Conc" and
        # "BH Prop Conc", and OCR returned the second without its B
        d = named(("Treating Pressure", "MPa"), ("Slurry Rate", "m3/min"),
                  ("Prop Conc", "kg/m3"), ("H Prop Conc", "kg/m3"))
        lib1._resolve_lost_letter(d)
        self.assertEqual(d[4]["name"], "BH Prop Conc")

    def test_a_bottomhole_sibling_names_this_one_wellhead(self):
        # the same rule the other way round — nothing here prefers an answer
        d = named(("Btm Prop Conc", "kg/m3"), ("H Prop Conc", "kg/m3"))
        lib1._resolve_lost_letter(d)
        self.assertEqual(d[2]["name"], "WH Prop Conc")

    def test_both_siblings_present_decides_nothing(self):
        d = named(("Prop Conc", "kg/m3"), ("BH Prop Conc", "kg/m3"),
                  ("H Prop Conc", "kg/m3"))
        lib1._resolve_lost_letter(d)
        self.assertEqual(d[3]["name"], "H Prop Conc")

    def test_no_sibling_decides_nothing(self):
        d = named(("Treating Pressure", "MPa"), ("H Prop Conc", "kg/m3"))
        lib1._resolve_lost_letter(d)
        self.assertEqual(d[2]["name"], "H Prop Conc")

    def test_a_sibling_on_another_unit_is_not_a_sibling(self):
        d = named(("Prop Conc", "L/m3"), ("H Prop Conc", "kg/m3"))
        lib1._resolve_lost_letter(d)
        self.assertEqual(d[2]["name"], "H Prop Conc")

    def test_two_mangled_entries_decide_nothing(self):
        # which of the two is which is exactly what is not known
        d = named(("Prop Conc", "kg/m3"), ("H Prop Conc", "kg/m3"),
                  ("H Prop Conc", "kg/m3"))
        lib1._resolve_lost_letter(d)
        self.assertEqual([v["name"] for v in d.values()],
                         ["Prop Conc", "H Prop Conc", "H Prop Conc"])

    def test_names_that_were_read_whole_are_never_touched(self):
        d = named(("Prop Conc", "kg/m3"), ("Btm Prop Conc", "kg/m3"),
                  ("Treating Pressure", "MPa"), ("GORV Pressure", "MPa"))
        before = [v["name"] for v in d.values()]
        lib1._resolve_lost_letter(d)
        self.assertEqual([v["name"] for v in d.values()], before)

    def test_an_additive_code_is_not_a_proppant_concentration(self):
        # the ambiguous name is matched exactly, not approximately
        d = named(("Prop Conc", "kg/m3"), ("475 CONC", "kg/m3"))
        lib1._resolve_lost_letter(d)
        self.assertEqual(d[2]["name"], "475 CONC")


if __name__ == "__main__":
    unittest.main()


def pts(pairs):
    """(value, position) -> the (value, cx, cy) triples the ladder works in."""
    return [(float(v), float(x), 80.0) for v, x in pairs]


# 00919's rate ladders step one gridline, and the sheet's ladders step 64.98.
GRID = 64.98


class ATickLabelThatLostCharacters(unittest.TestCase):
    def test_00919_p129_stage_12_drops_the_truncated_20(self):
        # [2, 16, 12] off an axis printed 20/16/12/8/4/0
        got = lib1._drop_a_lost_digit(
            pts([(2, 147.60), (16, 212.58), (12, 277.56)]), GRID)
        self.assertEqual([v for v, _x, _y in got], [16.0, 12.0])

    def test_00919_p143_drops_the_truncated_30(self):
        # [3, 24, 18, 12] off an axis printed 30/24/18/12/6/0 — four labels,
        # which the ordinary rule accepts, so the 3 was fitted through
        got = lib1._drop_a_lost_digit(
            pts([(3, 147.60), (24, 212.58), (18, 277.74), (12, 341.64)]), GRID)
        self.assertEqual([v for v, _x, _y in got], [24.0, 18.0, 12.0])

    def test_an_axis_that_reads_whole_is_not_touched(self):
        # 00919 p119 reads all three of 20/16/12, and p109 all four of
        # 25/20/15/10 — nothing here may move them
        for p in (pts([(20, 147.42), (16, 212.40), (12, 277.20)]),
                  pts([(25, 147.42), (20, 212.40), (15, 277.20), (10, 341.10)])):
            self.assertEqual(lib1._drop_a_lost_digit(p, GRID), p)

    def test_a_ladder_with_a_tick_simply_missing_is_not_touched(self):
        # 1500/1200/900/300 — the 600 was never read, the spacing is uneven
        # because of it, and no label here is a truncation of anything
        p = pts([(1500, 142.0), (1200, 205.9), (900, 270.9), (300, 400.0)])
        self.assertEqual(lib1._drop_a_lost_digit(p, GRID), p)

    def test_a_prediction_the_label_does_not_start_with_is_refused(self):
        # same shape as p129 but the suspect reads 7, which "20" is not
        p = pts([(7, 147.60), (16, 212.58), (12, 277.56)])
        self.assertEqual(lib1._drop_a_lost_digit(p, GRID), p)

    def test_a_label_of_the_full_length_is_not_a_truncation(self):
        # 20 predicted, "20" read: nothing was lost, the ladder is simply not
        # one, and dropping a label that is right would invent an axis
        p = pts([(20, 147.60), (16, 212.58), (11, 277.56)])
        self.assertEqual(lib1._drop_a_lost_digit(p, GRID), p)

    def test_two_labels_are_left_to_the_pair_rule(self):
        p = pts([(16, 212.58), (12, 277.56)])
        self.assertEqual(lib1._drop_a_lost_digit(p, GRID), p)

    def test_five_labels_are_left_alone(self):
        # a full ladder is not this rule's business, even with a bad label in
        # it: there is no evidence here that only one of five is wrong
        p = pts([(3, 147.6), (24, 212.58), (18, 277.74), (12, 341.64),
                 (6, 406.62)])
        self.assertEqual(lib1._drop_a_lost_digit(p, GRID), p)

    def test_without_a_page_grid_the_three_label_case_still_works(self):
        # _even_run needs no grid; only the two-label remainder does
        got = lib1._drop_a_lost_digit(
            pts([(3, 147.60), (24, 212.58), (18, 277.74), (12, 341.64)]), None)
        self.assertEqual([v for v, _x, _y in got], [24.0, 18.0, 12.0])
        p = pts([(2, 147.60), (16, 212.58), (12, 277.56)])
        self.assertEqual(lib1._drop_a_lost_digit(p, None), p)


class EvenRun(unittest.TestCase):
    def test_a_printed_axis(self):
        self.assertTrue(lib1._even_run(pts([(25, 147.42), (20, 212.40),
                                            (15, 277.20), (10, 341.10)])))

    def test_values_that_turn_around(self):
        self.assertFalse(lib1._even_run(pts([(2, 147.6), (16, 212.58),
                                             (12, 277.56)])))

    def test_uneven_positions(self):
        self.assertFalse(lib1._even_run(pts([(30, 100.0), (20, 165.0),
                                             (10, 360.0)])))

    def test_two_points_are_not_a_run(self):
        self.assertFalse(lib1._even_run(pts([(16, 212.58), (12, 277.56)])))
