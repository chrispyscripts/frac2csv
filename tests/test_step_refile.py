"""STEP charts filed under a misread stage number, and long gaps bridged flat.

00243 (#819) filed seven intervals' charts as "3"; 00248 (#823) its first
three as "5". 00244 Stage 32 (#816): a 20-minute gap between a curve resting
on the floor and the curve pumping was bridged as one long slant, an X across
the chart with its neighbour.

  python3 -m unittest tests.test_step_refile
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402

NAN = float("nan")


def chart(stage, top, page):
    return {"type": "series", "source": "STEP surface chart (raster)", "page": page,
            "meta": {"stage": stage, "title": f"Interval {stage} (surface)", "top_m": top}}


class Refile(unittest.TestCase):
    def test_a_chart_under_a_busy_number_goes_to_its_intervals_owner(self):
        rs = [chart("3", 3000.0, 23), chart("3", 3000.0, 24),     # stage 3's own
              chart("3", 2900.0, 45),                              # stage 13's, misread
              chart("13", 2900.0, 46)]                             # stage 13's offset
        notes = []
        self.assertEqual(pipeline._step_stage_depth_conflicts(rs, notes), 1)
        self.assertEqual(rs[2]["meta"]["stage"], "13")
        self.assertEqual(rs[2]["meta"]["title"], "Interval 13 (surface)")
        self.assertEqual(rs[0]["meta"]["stage"], "3")

    def test_an_unowned_interval_between_two_apart_takes_the_number_between(self):
        rs = [chart("31", 2800.0, 1), chart("33", 2720.0, 2),
              chart("2", 2760.0, 3), chart("2", 3500.0, 4), chart("2", 3500.0, 5)]
        pipeline._step_stage_depth_conflicts(rs, [])
        self.assertEqual(rs[2]["meta"]["stage"], "32")

    def test_the_daily_summary_settles_it_first(self):
        rs = [chart("5", 5637.2, 23), chart("5", 5600.0, 25), chart("5", 5500.0, 33)]
        table = [(5637.2, "1"), (5600.0, "2"), (5500.0, "5")]
        with mock.patch.object(pipeline, "_summary_depths", return_value=table):
            pipeline._step_stage_depth_conflicts(rs, [], doc=object())
        self.assertEqual([r["meta"]["stage"] for r in rs], ["1", "2", "5"])

    def test_one_interval_per_number_is_left_alone(self):
        rs = [chart("1", 3000.0, 1), chart("2", 2900.0, 2)]
        self.assertEqual(pipeline._step_stage_depth_conflicts(rs, []), 0)


class StageFromOrder(unittest.TestCase):
    def pages(self, stages):
        return [{"type": "series", "source": "STEP surface chart (raster)", "page": p,
                 "meta": {"stage": st, "title": f"Interval {st or '?'} (surface)"}}
                for p, st in stages]

    def test_unread_pages_between_take_their_place(self):
        rs = self.pages([(76, "1"), (77, ""), (78, ""), (79, "4")])
        self.assertEqual(pipeline._step_stage_from_order(rs, []), 2)
        self.assertEqual([r["meta"]["stage"] for r in rs], ["1", "2", "3", "4"])
        self.assertEqual(rs[1]["meta"]["title"], "Interval 2 (surface)")

    def test_a_number_out_of_order_is_read_again(self):
        # 00347 p85 read "1" between 7 and 11
        rs = self.pages([(82, "7"), (83, "8"), (84, "9"), (85, "1"), (86, "11")])
        pipeline._step_stage_from_order(rs, [])
        self.assertEqual(rs[3]["meta"]["stage"], "10")

    def test_a_gap_that_does_not_add_up_is_left_alone(self):
        # two pages per stage (a treatment and an offset chart)
        rs = self.pages([(19, "1"), (20, "1"), (21, ""), (22, ""), (23, "3"), (24, "3")])
        self.assertEqual(pipeline._step_stage_from_order(rs, []), 0)

    def test_retreatments_are_not_anchors(self):
        rs = self.pages([(35, "1.1"), (37, ""), (39, "2")])
        self.assertEqual(pipeline._step_stage_from_order(rs, []), 0)

    def test_a_book_of_two_pages_a_stage_is_left_as_read(self):
        # 00185: a treatment and an offset chart per stage, both numbered
        # right; p47's "11" was pushed on to 12 as out of order
        rs = self.pages([(44, "10"), (45, "10"), (46, "11"), (47, "11"),
                         (48, "12"), (49, "12"), (50, "15"), (51, "15")])
        self.assertEqual(pipeline._step_stage_from_order(rs, []), 0)
        self.assertEqual(rs[3]["meta"]["stage"], "11")


class StageFromSpacing(unittest.TestCase):
    """00347 (#811): one stage per page, about 50.8 m apart, toe first."""

    def book(self, stages):
        return [chart(st, top, p) for p, st, top in stages]

    def test_misread_and_unread_charts_take_the_number_their_depth_falls_on(self):
        rs = self.book([(76, "1", 3309.18), (77, "2", 3255.82), (91, "16", 2545.10),
                        (92, "17", 2494.03), (93, "1", 2443.08), (94, "1", 2392.44),
                        (95, "", 2342.06), (96, "", 2342.06), (97, "21", 2290.86),
                        (98, "", 2239.87), (101, "25", 2087.26), (104, "", 1934.34)])
        notes = []
        pipeline._step_stage_from_spacing(rs, notes)
        self.assertEqual([r["meta"]["stage"] for r in rs],
                         ["1", "2", "16", "17", "18", "19", "20", "20", "21", "22", "25", "28"])
        self.assertEqual(rs[4]["meta"]["title"], "Interval 18 (surface)")
        self.assertRegex(notes[0], r"50\.\d m a stage")

    def test_a_depth_between_two_stages_is_left_alone(self):
        rs = self.book([(1, "1", 3000.0), (2, "2", 2950.0), (3, "3", 2900.0),
                        (4, "4", 2850.0), (5, "", 2825.0)])
        self.assertEqual(pipeline._step_stage_from_spacing(rs, []), 0)

    def test_a_retreatment_keeps_its_number(self):
        rs = self.book([(1, "1", 3000.0), (2, "2", 2950.0), (3, "3", 2900.0),
                        (4, "4", 2850.0), (5, "2.1", 2950.0)])
        pipeline._step_stage_from_spacing(rs, [])
        self.assertEqual(rs[4]["meta"]["stage"], "2.1")

    def test_a_book_printing_one_depth_for_several_stages_is_left_alone(self):
        # 00185 prints the same interval on 11 and 12, 13 and 14, ...
        rs = self.book([(1, "9", 4254.04), (2, "10", 4197.01), (3, "11", 4140.24),
                        (4, "12", 4140.24), (5, "13", 4083.61), (6, "14", 4083.61),
                        (7, "15", 3914.51), (8, "16", 3914.51), (9, "", 4000.0)])
        self.assertEqual(pipeline._step_stage_from_spacing(rs, []), 0)


class LongGapOnTheFloor(unittest.TestCase):
    def chart(self, data):
        n = len(next(iter(data.values())))
        return {"type": "series", "source": "STEP surface chart (raster)", "page": 7,
                "meta": {"stage": "1"}, "samples": np.arange(n, dtype=float),
                "data": {k: np.asarray(v, float) for k, v in data.items()},
                "scales": {k: (16.0, 0.0) for k in data},
                "frames": {k: (16.0, 0.0) for k in data}, "deduced": {}}

    def test_a_long_gap_from_rest_to_pumping_runs_along_the_floor(self):
        gap = pipeline.STEP_FLOOR_GAP_S + 120
        q = [0.0] * 30 + [NAN] * gap + [8.0] * 30
        r = self.chart({"Slurry Rate": q})
        pipeline._bridge_step_gaps([r], [])
        v = r["data"]["Slurry Rate"]
        self.assertTrue(np.isfinite(v).all())
        self.assertTrue(np.allclose(v[30:30 + gap], 0.0))

    def test_a_short_gap_is_still_a_slant(self):
        q = [0.0] * 30 + [NAN] * 60 + [8.0] * 30
        r = self.chart({"Slurry Rate": q})
        pipeline._bridge_step_gaps([r], [])
        v = r["data"]["Slurry Rate"]
        self.assertGreater(v[60], 1.0)


if __name__ == "__main__":
    unittest.main()
