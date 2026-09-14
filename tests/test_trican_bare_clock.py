"""The 2015 Trican stage table: a 12-hour clock with no AM/PM (00015, #639).

  python3 -m unittest tests.test_trican_bare_clock
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trican2                                             # noqa: E402

# 00015's eleven stages exactly as the sheets print them
BARE = [(1, 3, 0, None), (2, 4, 29, None), (3, 5, 32, None), (4, 12, 0, None),
        (5, 8, 27, None), (6, 9, 40, None), (7, 10, 41, None), (8, 11, 51, None),
        (9, 12, 44, None), (10, 1, 48, None), (11, 2, 48, None)]


class Resolve(unittest.TestCase):

    def test_00015_anchored_by_the_day_sheet(self):
        # "Start Time: 3:01 pm" on Day 1 - July 6 says 03:00 is 3 PM
        out = trican2.resolve_bare(BARE, anchors=[15 * 60 + 1], start_date=date(2015, 7, 6))
        self.assertEqual((out[1]["date"], out[1]["start"]), ("2015-07-06", "15:00:00"))
        self.assertEqual((out[3]["date"], out[3]["start"]), ("2015-07-06", "17:32:00"))
        self.assertEqual((out[4]["date"], out[4]["start"]), ("2015-07-07", "00:00:00"))   # midnight, next day
        self.assertEqual((out[5]["date"], out[5]["start"]), ("2015-07-07", "08:27:00"))
        self.assertEqual((out[9]["date"], out[9]["start"]), ("2015-07-07", "12:44:00"))
        self.assertEqual((out[10]["date"], out[10]["start"]), ("2015-07-07", "13:48:00"))
        self.assertIn("anchored by the day sheet", out[1]["resolved"])
        # monotonic across the job
        stamps = [(out[k]["date"], out[k]["start"]) for k in sorted(out)]
        self.assertEqual(stamps, sorted(stamps))

    def test_without_an_anchor_00015_is_a_tie_and_says_so(self):
        # both halves of the day give a 23.8-hour job; the rule cannot know,
        # takes the morning, and labels the guess
        out = trican2.resolve_bare(BARE, anchors=[], start_date=date(2015, 7, 6))
        self.assertEqual(out[1]["start"], "03:00:00")
        self.assertIn("GUESS", out[1]["resolved"])

    def test_the_shorter_job_wins_when_the_halves_differ(self):
        # 10:00, 11:00, 09:30: morning gives 10:00 -> 21:30 (11.5 h);
        # evening gives 22:00 -> 09:30 next day (11.5 h) — no; make it clear:
        bare = [(1, 10, 0, None), (2, 11, 0, None), (3, 1, 0, None)]
        out = trican2.resolve_bare(bare)
        self.assertEqual([out[k]["start"] for k in (1, 2, 3)], ["10:00:00", "11:00:00", "13:00:00"])

    def test_a_morning_job_stays_in_the_morning(self):
        out = trican2.resolve_bare([(1, 8, 0, None), (2, 9, 30, None), (3, 11, 0, None), (4, 1, 15, None)])
        self.assertEqual([out[k]["start"] for k in (1, 2, 3, 4)],
                         ["08:00:00", "09:30:00", "11:00:00", "13:15:00"])
        self.assertEqual(out[1]["date"], "")                    # no job date printed: no date invented

    def test_an_explicit_am_pm_on_a_row_is_obeyed(self):
        out = trican2.resolve_bare([(1, 3, 0, "P"), (2, 4, 29, None)])
        self.assertEqual([out[1]["start"], out[2]["start"]], ["15:00:00", "16:29:00"])

    def test_the_anchor_must_be_within_ten_minutes(self):
        # an 11:40 am day-sheet clock says nothing about a table starting 03:00
        out = trican2.resolve_bare(BARE, anchors=[11 * 60 + 40])
        self.assertNotIn("anchored", out[1]["resolved"])


class ChainOrder(unittest.TestCase):
    """00041 (#645): stage 23 was pumped between 18 and 19."""

    ROWS = [(18, 5, 53, None, (6, 45)), (19, 7, 37, None, (8, 26)), (20, 8, 26, None, (9, 12)),
            (21, 9, 12, None, (9, 58)), (22, 9, 58, None, (10, 44)), (23, 6, 45, None, (7, 37)),
            (24, 10, 44, None, (11, 25)), (25, 11, 25, None, (12, 10)), (26, 12, 10, None, (12, 52))]

    def test_the_chain_puts_23_between_18_and_19(self):
        self.assertEqual([b[0] for b in trican2._chain_order(self.ROWS)], [18, 23, 19, 20, 21, 22, 24, 25, 26])

    def test_resolved_along_the_chain_nothing_jumps_twelve_hours(self):
        out = trican2.resolve_bare(self.ROWS, anchors=[5 * 60 + 53], start_date=date(2015, 11, 13))
        self.assertEqual(out[23]["start"], "06:45:00")            # not 18:45
        self.assertEqual(out[19]["start"], "07:37:00")
        self.assertEqual(out[24]["start"], "10:44:00")            # not 22:44
        self.assertEqual(out[26]["start"], "12:10:00")            # noon, same day
        self.assertEqual({out[k]["date"] for k in out}, {"2015-11-13"})
        self.assertIn("order of pumping", out[23]["resolved"])

    def test_without_finishes_the_stage_order_stands(self):
        rows = [(1, 3, 0, None), (2, 4, 29, None)]
        self.assertEqual([b[0] for b in trican2._chain_order(rows)], [1, 2])
        out = trican2.resolve_bare(rows, anchors=[15 * 60 + 1])
        self.assertIn("order of stages", out[1]["resolved"])

    def test_a_gap_in_the_chain_continues_in_stage_order(self):
        rows = [(15, 12, 41, None, (1, 38)), (16, 4, 5, None, (4, 58)), (17, 4, 58, None, (5, 53))]
        self.assertEqual([b[0] for b in trican2._chain_order(rows)], [15, 16, 17])


class Parse(unittest.TestCase):

    def test_bare_and_marked_forms(self):
        for text, want in (("05:32", ("05", "32", None)), (" 3:05 pm", ("3", "05", "p")),
                           ("11:15 A.M.", ("11", "15", "A")), ("12/02 05:32", None), ("-", None)):
            m = trican2._BARE_START.match(text)
            self.assertEqual(None if m is None else (m.group(1), m.group(2), m.group(3)), want, text)

    def test_the_long_date_and_the_day_anchor(self):
        self.assertTrue(trican2._JOB_START.search("Start Date: July 06, 2015  End Date: July 07, 2015"))
        m = trican2._DAY_ANCHOR.search("Day 1 - July 6, 2015\nStart Time: 3:01 pm\nEnd Time: 7:31 pm")
        self.assertEqual((m.group(1), m.group(2), m.group(3)), ("3", "01", "p"))


if __name__ == "__main__":
    unittest.main()
