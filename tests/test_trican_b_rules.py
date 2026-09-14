"""Trican layout B: the dotted gridline goes, the curve lying along it stays.

  python3 -m unittest tests.test_trican_b_rules

01350 p187 (#638): WH Prop Conc is drawn in the same olive as its gridlines,
and a proppant schedule holds at 100, 200, 300 kg/m3 — on the rules. The
stripper blanked rule rows whole and took every hold with them: 214 of the
channel's 637 inked columns, against 2 lost at the tracer.
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican_charts as tc                                # noqa: E402

X0, X1, Y0, Y1 = 59, 791, 9, 418
RULE = 214


def dotted_row(width, on=1, off=1):
    row = np.zeros(width, bool)
    row[X0 + 5:X1 - 5:on + off] = True
    return row


class StripRules(unittest.TestCase):

    def mask(self):
        m = np.zeros((Y1 + 10, X1 + 10), bool)
        m[RULE] = dotted_row(m.shape[1])                   # the rule: 1-on-1-off
        m[RULE - 1, 300:303] = True                         # a hair of halo
        return m

    def test_a_dotted_rule_row_is_a_rule(self):
        self.assertTrue(tc._is_rule_row(self.mask(), RULE, X0, X1))

    def test_the_dashes_go_and_the_hold_stays(self):
        m = self.mask()
        m[RULE - 1:RULE + 2, 400:560] = True               # a 160 px hold, pen 3 px, ON the rule
        masks = {"wh_conc": m}
        tc._strip_rules(masks, [RULE], X0, Y0, X1, Y1)
        row = masks["wh_conc"][RULE]
        self.assertTrue(row[400:560].all(), "the hold was stripped")
        self.assertFalse(row[X0 + 5:390].any(), "dashes survived to the left")
        self.assertFalse(row[570:X1 - 5].any(), "dashes survived to the right")
        self.assertTrue(masks["wh_conc"][RULE - 1, 400:560].all())
        self.assertTrue(masks["wh_conc"][RULE + 1, 400:560].all())
        self.assertFalse(masks["wh_conc"][RULE - 1, 300:303].any(), "the halo survived")

    def test_a_crossing_loses_its_three_pixels_as_before(self):
        m = self.mask()
        m[RULE, 500:503] = True                             # the curve crossing the rule steeply
        m[RULE - 4:RULE, 497:500] = True                    # …coming from above
        masks = {"wh_conc": m}
        tc._strip_rules(masks, [RULE], X0, Y0, X1, Y1)
        self.assertFalse(masks["wh_conc"][RULE, 500:503].any())   # bridged by curve_positions later
        self.assertTrue(masks["wh_conc"][RULE - 4:RULE - 1, 497:500].all())   # untouched off the band

    def test_a_row_that_is_not_a_rule_is_untouched(self):
        m = np.zeros((Y1 + 10, X1 + 10), bool)
        m[RULE, 100:700] = True                             # a solid line: not dashed, not a rule here
        masks = {"wh_conc": m}
        tc._strip_rules(masks, [RULE], X0, Y0, X1, Y1)
        self.assertTrue(masks["wh_conc"][RULE, 100:700].all())


if __name__ == "__main__":
    unittest.main()
