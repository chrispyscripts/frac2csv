"""A STEP vector legend that prints the pressure curve as plain "Main".

Report #761 (2026-09-25, v1.11.27) reads "No TR pressure" against
00106-102011906303W600_0491147_COMP.pdf chart 1. The pressure was never
missing. The app's own channel table on that report lists it:

    | Main | MPa | 0..100 (frame -3.64..101) | 76.69 |

step_vec names a channel from its legend text with the trailing unit
stripped -- "Main (MPa)" -> "Main" -- and then every display and export path
resolves that name through the alias table. alias_table.txt knew "Mainline"
and "Main Pressure" but not bare "Main", so the curve arrived traced,
calibrated against its own 0..100 MPa ladder and clipped to the frame, and
was filed as an unrecognised extra channel. The Tr Press column shipped
empty and the chart looked like it had lost its pressure.

Four vendors already spell this curve with the same stem -- Canyon-1 and
SanJel-1 "Main Pressure", Step-2 "Mainline", Trican-2 "Mainline Pressure" --
and nothing in the table maps a "Main..." name to a rate or a concentration,
which is what makes the bare word safe to add. Lookups merge across template
sections, so a word added under Step-2 answers for every reader.

The three guards below matter more than the mapping itself:

  * the CHEMICAL channels on the same chart stay unmapped. "BIO Conc." and
    "HYD FR Conc 2" are real STEP series with no canonical column, and an
    alias pass that started sweeping them into our four would be a worse bug
    than the one being fixed.
  * "Mainline 3" stays unmapped. That is report #111, where Carmine's
    instruction was "do not try ti get mainline 3 same colors as cocn" -- a
    decision to leave that curve alone, recorded here so a later widening of
    the alias table cannot quietly swallow it.
  * "Main Treatment" stays unmapped. Halliburton IFS titles its charts
    "Interval 7 - Main Treatment" and ifs_tables matches the word as a phase
    name; it is furniture, never a curve, and must not resolve to a channel.

  python3 -m unittest tests.test_step_vec_main_alias
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aliases                                               # noqa: E402


class MainIsTreatingPressure(unittest.TestCase):

    def test_the_legend_word_on_761_resolves(self):
        self.assertEqual(aliases.canon("Main"), "Tr Press")

    def test_it_resolves_however_the_page_cases_and_spaces_it(self):
        for raw in ("main", "MAIN", " Main ", "Main "):
            self.assertEqual(aliases.canon(raw), "Tr Press", repr(raw))

    def test_the_longer_spellings_still_resolve(self):
        for raw in ("Mainline", "Main Pressure", "Mainline Pressure",
                    "Surface Pressure"):
            self.assertEqual(aliases.canon(raw), "Tr Press", repr(raw))

    def test_the_rest_of_chart_1_is_unchanged(self):
        # every other channel #761 lists, as the report spells them
        self.assertEqual(aliases.canon("Prop Conc"), "WH Prop Conc")
        self.assertEqual(aliases.canon("Btm Prop Conc"), "BH Prop Conc")
        self.assertEqual(aliases.canon("Slurry Rate"), "Slurry Rate")


class WhatMustNotBeSweptUp(unittest.TestCase):

    def test_the_chemical_channels_stay_unmapped(self):
        for raw in ("BIO Conc.", "HYD FR Conc 2"):
            self.assertIsNone(aliases.canon(raw), repr(raw))

    def test_mainline_3_stays_unmapped(self):
        """#111: Carmine asked for this curve to be left alone."""
        self.assertIsNone(aliases.canon("Mainline 3"))

    def test_a_chart_title_phase_is_not_a_curve(self):
        """IFS titles pages "Interval 7 - Main Treatment"."""
        self.assertIsNone(aliases.canon("Main Treatment"))
        self.assertIsNone(aliases.canon("Entire Treatment"))


class TheTableItself(unittest.TestCase):

    def test_main_is_declared_under_step_2(self):
        """Scoped where it was found, so the next reader of the table can
        see which template asked for it."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmpl, line = None, None
        with open(os.path.join(here, "alias_table.txt"), encoding="utf-8") as f:
            for raw in f:
                s = raw.strip()
                if s and "=" not in s and not s.lower().startswith(("alias", "units")):
                    tmpl = s
                if tmpl == "Step-2" and s.startswith("curve.Tr Press"):
                    line = s
        self.assertIsNotNone(line, "Step-2 has no curve.Tr Press line")
        names = [n.strip().lower() for n in line.split("=", 1)[1].split(",")]
        self.assertIn("main", names)


if __name__ == "__main__":
    unittest.main()
