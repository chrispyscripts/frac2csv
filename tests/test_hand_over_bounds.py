"""Where the hand-over may put a STEP chart placed from a filed start (00184-00186).

STEP's tiled 2017 books plot elapsed minutes, so each chart is put on the
clock at the Daily Stage Summary's filed start and _hand_over_tails then moves
it to line up with the chart before, where the two re-plot the same minutes.
The search is centred on the lag the chart before settled on, because on
00180 the charts' own clock drifts a few percent from the filed minutes and a
run reached 1,179 s from its filed starts (test_hand_over.FiledToTheMinute).

Nothing stopped that walk. On 00184 the elapsed axes run ~12% ahead of the
filed clock; each pair settled a few minutes later than the last, 40 charts
moved by up to 4,697 s, and stage 12's surface chart opened at 19:07:51,
after stage 13's filed 18:38 and 78 min from its own chemical chart on the
same page. Measured on 1,489 STEP charts that print their own wall clock
beside a filed start, the window opens within 30 min of the filed start on
94%, and never at or after the next stage's filed start (0 of 1,442). Those
are the bounds (DriftIsBounded, NeverAfterTheNextStage).

The rest is what the bound exposed. The printed elapsed axes say where two
charts of one acquisition clock sit against each other, where the drift
search could only guess (PlacedByTheAxis). 00185 prints two pages per stage
on one window and reads them as one source (TwoFamiliesOneSource), and on
00186 a page's chemical plot never lines up by its own samples while its
surface plot does (OnePageOneAxis).

  python3 -m unittest tests.test_hand_over_bounds
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                            # noqa: E402

SRC = "STEP surface chart (raster)"

# white noise: aperiodic, so exactly one lag lines two charts up
JOB = 40.0 + 10.0 * np.random.default_rng(11).normal(size=900 * 60)
OFFSET = 20.0 + 5.0 * np.random.default_rng(12).normal(size=900 * 60)


def chart(stage, filed, at_min, minutes, source=SRC, pens=("Tr Press",)):
    """Stage `stage` filed at `filed`, its window really opening `at_min`
    minutes into the job and running `minutes`."""
    a, n = int(at_min * 60), int(minutes * 60)
    sig = {"Tr Press": JOB, "Slurry Rate": JOB * 0.2, "Prop Conc": JOB * 3.0,
           "BH Press": JOB * 1.4 + 9, "Annulus": JOB * 0.5 + 3,
           "K Casing": OFFSET, "L Casing": OFFSET * 1.5, "N Casing": OFFSET + 7}
    data = {p: sig[p][a:a + n].copy() for p in pens}
    md = {"title": f"Interval {stage}", "stage": str(stage), "date": "2017-04-10",
          "start_time": filed, "duration_min": minutes, "warnings": []}
    return pipeline._series(md, np.arange(n, dtype=float), data, source, page=1)


def opens(r):
    return r["meta"]["start_time"]


class DriftIsBounded(unittest.TestCase):
    """Filed an hour apart, each window really opening 12 min later against
    its filed start than the one before: the drift-following finds +12, +24,
    then +36 — and the last is beyond anything a STEP window does."""

    def setUp(self):
        self.a = chart(1, "06:00:00", 0, 85)
        self.b = chart(2, "07:00:00", 72, 85)
        self.c = chart(3, "08:00:00", 144, 85)
        self.d = chart(4, "09:00:00", 216, 85)

    def test_moves_within_the_bound_still_follow_the_drift(self):
        pipeline._hand_over_tails([self.a, self.b, self.c, self.d], [])
        self.assertEqual(opens(self.b), "07:12:00")
        self.assertEqual(opens(self.c), "08:24:00")      # 24 min: as 00180 does

    def test_a_move_past_the_bound_stops_at_it(self):
        notes = []
        pipeline._hand_over_tails([self.a, self.b, self.c, self.d], notes)
        self.assertEqual(opens(self.d), "09:30:00",
                         "moved further than 30 min off its filed start")
        self.assertTrue(any("as far as it may go" in w and "6.0 min later" in w
                            for w in self.d["meta"]["warnings"]))

    def test_the_chart_before_is_cut_only_where_the_next_one_re_plots(self):
        # stage 4's window opens 6 min after where it may be put. Cutting
        # stage 3 at the bound would throw away 6 min that no other chart
        # plots (on 00184 that is a stage's own treatment), so stage 3 hands
        # over only what stage 4 re-plots and the two overlap by the 6 min
        notes = []
        pipeline._hand_over_tails([self.a, self.b, self.c, self.d], notes)
        self.assertEqual(len(self.c["samples"]), 72 * 60)
        self.assertEqual(self.c["handover"]["to"], "4")
        self.assertEqual(len(self.c["handover"]["samples"]), 13 * 60)

    def test_the_bound_is_measured_from_the_filed_start_not_the_last_move(self):
        self.assertEqual(pipeline.HANDOVER_DRIFT_S, 1800.0)
        # 00180's longest real move was 1,179 s and test_the_search_follows
        # _the_drift moves 1,500 s: both inside it
        self.assertGreater(pipeline.HANDOVER_DRIFT_S, 1500)


class NeverAfterTheNextStage(unittest.TestCase):
    """B's samples line up with A at +12 min, but stage 3 is filed at 07:10:
    a chart of stage 2 cannot open after stage 3 has started."""

    def test_the_next_stage_bounds_the_move(self):
        a = chart(1, "06:00:00", 0, 85)
        b = chart(2, "07:00:00", 72, 60)
        c = chart(3, "07:10:00", 200, 60, source="STEP chemical chart (raster)",
                  pens=("Slurry Rate",))
        pipeline._hand_over_tails([a, b, c], [])
        self.assertEqual(opens(b), "07:09:59")
        self.assertEqual(len(a["samples"]), 72 * 60)        # cut at what b re-plots

    def test_without_it_the_same_pair_is_moved(self):
        a = chart(1, "06:00:00", 0, 85)
        b = chart(2, "07:00:00", 72, 60)
        c = chart(3, "08:20:00", 200, 60, source="STEP chemical chart (raster)",
                  pens=("Slurry Rate",))
        pipeline._hand_over_tails([a, b, c], [])
        self.assertEqual(opens(b), "07:12:00")
        self.assertEqual(len(a["samples"]), 72 * 60)

    def test_next_stage_filed_before_this_one_bounds_nothing(self):
        # filed times out of order say nothing about where B may sit
        a = chart(1, "06:00:00", 0, 85)
        b = chart(2, "07:00:00", 72, 60)
        c = chart(3, "05:00:00", 400, 30, source="STEP chemical chart (raster)",
                  pens=("Slurry Rate",))
        pipeline._hand_over_tails([a, b, c], [])
        self.assertEqual(opens(b), "07:12:00")

    def test_a_misprinted_chart_does_not_drag_the_bound(self):
        # 00197 p52 prints stage 15's window under stage 19: one chart of
        # the next stage far too early, two where the stage is filed
        a = chart(1, "06:00:00", 0, 85)
        b = chart(2, "07:00:00", 72, 60)
        c1 = chart(3, "03:00:00", 400, 30, source="STEP chemical chart (raster)",
                   pens=("Slurry Rate",))
        c2 = chart(3, "08:20:00", 500, 30, source="STEP chemical chart (raster)",
                   pens=("Prop Conc",))
        c3 = chart(3, "08:20:30", 600, 30, source="STEP other",
                   pens=("Prop Conc",))
        pipeline._hand_over_tails([a, b, c1, c2, c3], [])
        self.assertEqual(opens(b), "07:12:00")


def on_axis(r, minutes):
    """The chart's printed "Time (min)" axis opens at `minutes`."""
    r["axis_t0_s"] = minutes * 60.0
    return r


class PlacedByTheAxis(unittest.TestCase):
    """00184 stages 21 and 22: filed 05:04 and 05:54, but on the charts'
    own acquisition clock 22's window opens 90.4 min into 21's (p41 reads
    274.1, p42 364.5) — 21's window opens 36 min before its treatment, 22's
    4. The drift-following search, centred on the filed spacing with 15 min
    of reach, never found it: the pair disagreed, 21 ran 54 min into 22 and
    the Lab flagged 22."""

    def setUp(self):
        self.a = on_axis(chart(21, "05:04:00", 0, 104), 274.1)
        self.b = on_axis(chart(22, "05:54:00", 90.4, 57), 364.5)

    def test_the_axes_find_the_pair(self):
        pipeline._hand_over_tails([self.a, self.b], [])
        self.assertEqual(len(self.a["samples"]), int(90.4 * 60))
        self.assertEqual(self.a["handover"]["to"], "22")

    def test_a_run_s_first_chart_takes_its_share_of_the_move(self):
        # 22 cannot open 40.4 min after its filed start; 21 heads its run,
        # so its filed start is as much a guess, and it opens earlier instead
        pipeline._hand_over_tails([self.a, self.b], [])
        self.assertEqual(opens(self.b), "06:24:00")           # +30, the bound
        self.assertEqual(opens(self.a), "04:53:36")           # -10.4 min
        self.assertTrue(any("opened before its stage's filed start" in w
                            for w in self.a["meta"]["warnings"]))

    def test_the_samples_refine_a_label_read_short(self):
        # the axis origin is read off labels, and the reader's time scale
        # runs ~3% off them: the samples say where, to the second
        on_axis(self.b, 274.1 + 88.0)
        pipeline._hand_over_tails([self.a, self.b], [])
        self.assertEqual(len(self.a["samples"]), int(90.4 * 60))

    def test_a_restarted_clock_links_nothing(self):
        # a new job file restarts the acquisition clock: 00184 p53 reads 9.5
        # after p52's 1034.4
        on_axis(self.b, 9.5)
        self.assertIsNone(pipeline._axis_offset(self.a, self.b, 1.0))

    def test_samples_that_contradict_the_axes_are_kept_as_printed(self):
        self.b["data"]["Tr Press"] = self.b["data"]["Tr Press"][::-1].copy()
        pipeline._hand_over_tails([self.a, self.b], [])
        self.assertEqual(len(self.a["samples"]), 104 * 60)
        self.assertEqual(opens(self.b), "05:54:00")
        self.assertTrue(any("disagree" in w for w in self.a["meta"]["warnings"]))


class OnePageOneAxis(unittest.TestCase):
    """00186: each page's surface plot is placed by its samples (0.3-1% gap
    at the match), its chemical plot never is — the additive pens are read
    too noisily to agree anywhere — so the two plots of one page sat up to
    43 min apart. The chemical plot follows the surface plot of its page."""

    def setUp(self):
        noise = np.random.default_rng(13)
        self.s1 = on_axis(chart(1, "06:00:00", 0, 85), 100)
        self.s2 = on_axis(chart(2, "07:00:00", 72, 60), 172)
        chem = "STEP chemical chart (raster)"
        self.c1 = on_axis(chart(1, "06:00:00", 0, 85, source=chem,
                                pens=("Slurry Rate",)), 100)
        self.c2 = on_axis(chart(2, "07:00:00", 72, 60, source=chem,
                                pens=("Slurry Rate",)), 172)
        for c in (self.c1, self.c2):      # never the same values twice
            c["data"]["Slurry Rate"] = 5 + noise.normal(size=len(c["samples"]))
        for r, pg in ((self.s1, 21), (self.c1, 21), (self.s2, 22), (self.c2, 22)):
            r["page"] = pg

    def run_it(self):
        pipeline._hand_over_tails([self.s1, self.c1, self.s2, self.c2], [])

    def test_the_chemical_plot_takes_its_page_s_place(self):
        self.run_it()
        self.assertEqual(opens(self.s2), "07:12:00")
        self.assertEqual(opens(self.c2), "07:12:00")

    def test_and_is_cut_where_its_page_hands_over(self):
        self.run_it()
        self.assertEqual(len(self.s1["samples"]), 72 * 60)
        self.assertEqual(len(self.c1["samples"]), 72 * 60)
        self.assertEqual(self.c1["handover"]["to"], "2")

    def test_the_page_number_does_not_matter(self):
        # 00185 prints a stage's Treatment and Offset pages two pages apart
        # on one window
        self.c2["page"] = 23
        self.run_it()
        self.assertEqual(opens(self.c2), "07:12:00")

    def test_a_different_axis_is_a_different_window(self):
        on_axis(self.c2, 172 + 5)
        self.run_it()
        self.assertEqual(opens(self.c2), "07:00:00")


class WiderThanItsPage(unittest.TestCase):
    """00208 p29 (stage 8) prints its surface plot on 619-687 min and its
    chemical plot on 535-725 — three stages' chemistry under one title.
    Both were put on the clock at stage 8's filed start, sample 0 to sample
    0, and the chemical plot ran 131 min past stage 9's start."""

    CHEM = "STEP chemical chart (raster)"

    def setUp(self):
        self.c7 = on_axis(chart(7, "00:34:00", 0, 88.2, source=self.CHEM,
                                pens=("Slurry Rate",)), 534.3)
        self.s8 = on_axis(chart(8, "01:27:00", 0, 67.4), 619.4)
        self.c8 = on_axis(chart(8, "01:27:00", 0, 189.9, source=self.CHEM,
                                pens=("Slurry Rate",)), 533.9)
        self.c9 = on_axis(chart(9, "02:26:00", 0, 67.5, source=self.CHEM,
                                pens=("Slurry Rate",)), 684.5)

    def trim(self, *charts):
        per = {}
        for r in charts:
            per.setdefault(r["source"], []).append((pipeline._abs_start(r), r))
        placed = {id(r): t for items in per.values() for t, r in items}
        notes = []
        pipeline._trim_wide_plots(per, placed, notes)
        return notes

    def test_the_wide_plot_keeps_its_page_s_window(self):
        notes = self.trim(self.c7, self.s8, self.c8, self.c9)
        self.assertAlmostEqual(self.c8["axis_t0_s"] / 60, 619.4, places=1)
        self.assertAlmostEqual(len(self.c8["samples"]) / 60, 67.4, delta=0.1)
        self.assertEqual(opens(self.c8), "01:27:00")       # sample 0 = page's
        self.assertTrue(any("p29" in n or "stage 8" in n for n in notes))

    def test_only_where_the_neighbours_print_the_rest(self):
        self.trim(self.s8, self.c8, self.c9)                # no stage 7
        self.assertAlmostEqual(self.c8["axis_t0_s"] / 60, 533.9, places=1)
        self.assertAlmostEqual(len(self.c8["samples"]) / 60, 152.9, delta=0.1)

    def test_another_run_s_minutes_are_not_the_neighbours(self):
        # 00248 p131: an axis restarts between job files, so stage 1's chart
        # reads the same minutes as stage 55's
        far = on_axis(chart(1, "00:34:00", 0, 88.2, source=self.CHEM,
                            pens=("Slurry Rate",)), 534.3)
        self.trim(far, self.s8, self.c8, self.c9)
        self.assertAlmostEqual(self.c8["axis_t0_s"] / 60, 533.9, places=1)

    def test_a_frame_a_few_minutes_wide_is_left(self):
        c8 = on_axis(chart(8, "01:27:00", 0, 70.0, source=self.CHEM,
                           pens=("Slurry Rate",)), 617.0)
        self.trim(self.c7, self.s8, c8, self.c9)
        self.assertEqual(len(c8["samples"]), 70 * 60)


class TwoFamiliesOneSource(unittest.TestCase):
    """00185: Treatment and Offset Analysis both read as STEP surface charts,
    on one 104-min window per stage; stage 3 filed 74 min after stage 2."""

    def setUp(self):
        # pressures only: no rate or proppant, so _still_pumping_after has
        # nothing to say and the cut is where the next chart begins
        tp = ("Tr Press", "BH Press", "Annulus")
        op = ("Tr Press", "K Casing", "L Casing", "N Casing")
        self.t2 = chart(2, "21:04:00", 0, 104, pens=tp)
        self.o2 = chart(2, "21:04:00", 0, 104, pens=op)
        self.t3 = chart(3, "22:18:00", 74, 31, pens=tp)
        self.o3 = chart(3, "22:18:00", 74, 31, pens=op)

    def test_each_chart_hands_over_to_its_own_kind(self):
        pipeline._hand_over_tails([self.t2, self.o2, self.t3, self.o3], [])
        self.assertEqual(len(self.t2["samples"]), 74 * 60,
                         "stage 2's treatment chart ran on into stage 3")
        self.assertEqual(len(self.o2["samples"]), 74 * 60)
        self.assertEqual(self.t2["handover"]["to"], "3")

    def test_plots_of_one_page_are_not_each_other_s_hand_over(self):
        pipeline._hand_over_tails([self.t2, self.o2, self.t3, self.o3], [])
        for r in (self.t2, self.o2):
            self.assertFalse(any("cannot re-plot itself" in w
                                 for w in r["meta"]["warnings"]))

    def test_pens_named_differently_from_page_to_page_still_cut(self):
        # 00185 reads stage 6's treatment legend as "Series (cy)…" where
        # stage 5's reads "Prop Conc…": the page, not the pens, says which
        # plots go together
        self.t3["data"] = {"Tr Press": self.t3["data"]["Tr Press"],
                           "Series (cy)": self.t3["data"]["BH Press"]}
        pipeline._hand_over_tails([self.t2, self.o2, self.t3, self.o3], [])
        self.assertEqual(len(self.t2["samples"]), 74 * 60)
        self.assertEqual(len(self.o2["samples"]), 74 * 60)

    def test_of_the_page_before_the_plot_with_its_own_pens(self):
        # 00246: the Offset plot's "Surface Pressure" is drawn on its own
        # axis and never lines up with the Treatment plot's, so stage 3's
        # Treatment plot pairs with stage 2's Treatment plot, not the later
        # Offset one
        items = [[0, self.t2], [0, self.o2], [1, self.t3], [1, self.o3]]
        sibs = pipeline._page_siblings(items)
        self.assertIs(pipeline._handover_partner(items[:2], self.t3, sibs)[1],
                      self.t2)
        self.assertIs(pipeline._handover_partner(items[:2], self.o3, sibs)[1],
                      self.o2)

    def test_one_plot_per_page_is_paired_as_it_always_was(self):
        e2, e3 = [0, self.t2], [1, self.t3]
        self.assertIs(pipeline._handover_partner([e2], self.t3), e2)
        sibs = pipeline._page_siblings([e2, [0, self.o2], e3, [1, self.o3]])
        self.assertEqual(len(sibs[id(self.t2)]), 1)
        self.assertNotIn(id(self.t2), {id(x[1]) for x in sibs[id(self.t3)]})


if __name__ == "__main__":
    unittest.main()
