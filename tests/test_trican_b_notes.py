"""A layout-B reader's notes: drops to the file, the rest to the stage (#648).

  python3 -m unittest tests.test_trican_b_notes
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                            # noqa: E402


class RouteNotes(unittest.TestCase):

    def test_only_an_unreadable_axis_is_a_drop(self):
        notes = ["WH Prop Conc: rate axis unreadable",
                 "WH Prop Conc: drawn from 18% to 94% of the chart's width, with 0 gap(s) "
                 "inside that span. Outside it the chart draws no curve",
                 "Prop Conc: no ticks on the concentration axis, so it is read from the "
                 "rate axis x100 — checked against this page's printed Conc Maximum",
                 "chart window wider than the stage; trimmed to the Start Time and Elapsed "
                 "Time the page prints"]
        drops, mine = pipeline._route_b_notes(notes)
        self.assertEqual(drops, [notes[0]])
        self.assertEqual(mine, notes[1:])

    def test_nothing_is_nothing(self):
        self.assertEqual(pipeline._route_b_notes(()), ([], []))


if __name__ == "__main__":
    unittest.main()
