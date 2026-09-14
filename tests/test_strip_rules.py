"""Gridline stripping: the mask answers, not the row's dominant colour.

Trican layout B tints each axis's dotted rules to match that axis's curve, so
the rules are the same colours as the traces and land in the traces' masks. The
stripper has to take the rule out and leave the curve in.

The case this pins down is 00981 p153. Row 61 carries the WH Prop Conc rule as
117 one-pixel dashes AND a WH Slurry Rate curve. The old code picked the row's
dominant dark colour to decide whose rule it was; the blue curve out-inks 117
dashes, so the answer came back (78,173,228), 236 away from the olive (92,97,5)
against a radius of 42, and nothing was stripped. The rule reached the export as
698.3 kg/m3 where the page prints a Conc Maximum of 456.2 (Carmine, #634).

A row holding two things has no one dominant colour. Ask each series' own mask.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc


X0, Y0, X1, Y1 = 5, 0, 395, 119


def _masks(h=120, w=400):
    return {k: np.zeros((h, w), bool) for k, *_ in tc.B_SERIES}


class RuleRow(unittest.TestCase):
    """What _is_rule_row must and must not call a rule."""

    def _row(self, starts, run=1, w=400):
        m = np.zeros((1, w), bool)
        for s0 in starts:
            m[0, s0:s0 + run] = True
        return m

    def test_a_regular_dotted_rule_is_a_rule(self):
        m = self._row(range(10, 390, 2))
        self.assertTrue(tc._is_rule_row(m, 0, X0, X1))

    def test_a_two_on_two_off_rule_is_a_rule(self):
        """The test asks that there IS a beat, never what the beat is."""
        m = self._row(range(10, 390, 4), run=2)
        self.assertTrue(tc._is_rule_row(m, 0, X0, X1))

    def test_a_dotted_curve_is_not_a_rule(self):
        """00981 p120: the mainline trace, dashed but not on a beat."""
        starts, x = [], 10
        for i in range(120):
            starts.append(x)
            x += 3 + (i % 5)          # intervals 3..7, none of them modal
        m = self._row(starts)
        self.assertFalse(tc._is_rule_row(m, 0, X0, X1),
                         "a dotted curve passed the beat test")

    def test_a_solid_curve_is_not_a_rule(self):
        m = np.zeros((1, 400), bool)
        m[0, 40:360] = True
        self.assertFalse(tc._is_rule_row(m, 0, X0, X1))


class StripRules(unittest.TestCase):

    def test_rule_stripped_though_another_series_out_inks_the_row(self):
        """00981 p153: olive rule and blue curve share row 61."""
        m = _masks()
        m["wh_conc"][61, 10:390:2] = True        # 190 dashes, the rule
        m["wh_rate"][60:63, 40:360] = True       # a solid curve, more ink
        tc._strip_rules(m, [61], X0, Y0, X1, Y1)
        self.assertFalse(m["wh_conc"].any(),
                         "the rule survived because another series out-inked it")

    def test_a_curve_on_a_reported_gridline_row_is_kept(self):
        """00583 p33: rows 132 and 136 are adjacent and only 132 is a rule."""
        m = _masks()
        m["wh_conc"][61, 10:390:2] = True        # the rule
        m["wh_rate"][61, 40:360] = True          # a curve lying ALONG the rule
        tc._strip_rules(m, [61], X0, Y0, X1, Y1)
        self.assertFalse(m["wh_conc"].any())
        self.assertEqual(int(m["wh_rate"].sum()), 320,
                         "the rate curve was blanked with the rule above it")

    def test_ink_one_row_off_the_reported_gridline_is_still_found(self):
        """b_box reports 60, 61, 62 and 63 for the same rule across 00981.

        p120 reports 63 for ink that sits at 61, which is why the search is 3
        and not 1: at 1 that page kept a gridline and exported it as 698.3.
        """
        for reported in (58, 59, 60, 61, 62, 63, 64):
            m = _masks()
            m["wh_conc"][61, 10:390:2] = True
            tc._strip_rules(m, [reported], X0, Y0, X1, Y1)
            self.assertFalse(m["wh_conc"].any(),
                             f"rule at 61 missed when reported at {reported}")

    def test_nothing_is_touched_away_from_a_reported_gridline(self):
        m = _masks()
        m["wh_conc"][61, 10:390:2] = True
        tc._strip_rules(m, [200], X0, Y0, X1, Y1)
        self.assertEqual(int(m["wh_conc"].sum()), 190)


if __name__ == "__main__":
    unittest.main()
