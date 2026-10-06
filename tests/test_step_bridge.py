"""STEP: no broken stretches in a curve the chart draws whole.

  python3 -m unittest tests.test_step_bridge
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402

NAN = float("nan")


def chart(data, source="STEP surface chart (raster)", axes=None):
    n = len(next(iter(data.values())))
    return {"type": "series", "source": source, "page": 7, "meta": {"stage": "1"},
            "samples": np.arange(n, dtype=float),
            "data": {k: np.asarray(v, float) for k, v in data.items()},
            "scales": axes or {}, "frames": axes or {}, "deduced": {}}


class Bridge(unittest.TestCase):

    def run1(self, r):
        notes = []
        pipeline._bridge_step_gaps([r], notes)
        return r, notes

    def test_a_mid_flight_gap_is_interpolated_and_marked(self):
        p = [60.0] * 10 + [NAN] * 5 + [70.0] * 10
        r, notes = self.run1(chart({"Surface Pressure": p}, axes={"Surface Pressure": (100.0, 0.0)}))
        v = r["data"]["Surface Pressure"]
        self.assertTrue(np.isfinite(v).all())
        self.assertAlmostEqual(v[12], 60 + 10 * 3 / 6, places=6)
        self.assertEqual(int(r["deduced"]["Surface Pressure"].sum()), 5)
        self.assertTrue(any("bridged" in n for n in notes))

    def test_a_curve_resting_on_the_floor_is_carried_to_where_the_chart_ends(self):
        # pressure falls to 0.4 at sample 9 and the ink stops; the rate curve
        # carries on to sample 19; after that the frame is empty
        p = [60.0] * 9 + [0.4] + [NAN] * 15
        q = [8.0] * 15 + [0.1] * 5 + [NAN] * 5
        r, _ = self.run1(chart({"Surface Pressure": p, "Slurry Rate": q},
                               axes={"Surface Pressure": (100.0, 0.0), "Slurry Rate": (16.0, 0.0)}))
        v = r["data"]["Surface Pressure"]
        self.assertTrue(np.isfinite(v[:20]).all())
        self.assertTrue(np.allclose(v[10:20], 0.4))
        self.assertTrue(np.isnan(v[20:]).all(), "the empty margin stays empty")

    def test_a_lead_on_the_floor_starts_where_the_chart_starts(self):
        c = [NAN] * 3 + [NAN] * 7 + [0.0] * 5 + [300.0] * 10
        q = [NAN] * 3 + [5.0] * 22
        r, _ = self.run1(chart({"Prop Conc": c, "Slurry Rate": q},
                               axes={"Prop Conc": (1000.0, 0.0), "Slurry Rate": (16.0, 0.0)}))
        v = r["data"]["Prop Conc"]
        self.assertTrue(np.isnan(v[:3]).all())
        self.assertTrue(np.allclose(v[3:10], 0.0))

    def test_a_pressure_that_stops_in_mid_air_holds_its_last_reading(self):
        # the shutdown's near-vertical stroke is not traced; pressure holds
        # near its shut-in level, it does not fall to zero
        p = [60.0] * 9 + [27.7] + [NAN] * 10
        q = [8.0] * 20
        r, notes = self.run1(chart({"Surface Pressure": p, "Slurry Rate": q},
                                   axes={"Surface Pressure": (100.0, 0.0), "Slurry Rate": (16.0, 0.0)}))
        self.assertTrue(np.allclose(r["data"]["Surface Pressure"][10:], 27.7))
        self.assertTrue(any("mid-air" in n for n in notes))

    def test_a_rate_that_stops_in_mid_air_drops_to_the_floor(self):
        q = [8.0] * 9 + [6.6] + [NAN] * 10
        c = [1.5] * 20
        r, _ = self.run1(chart({"Slurry Rate": q, "Btm Prop Conc": c},
                               axes={"Slurry Rate": (25.0, 0.0), "Btm Prop Conc": (500.0, 0.0)}))
        self.assertTrue(np.allclose(r["data"]["Slurry Rate"][10:], 0.0))

    def test_a_curve_that_starts_in_mid_air_rose_from_the_floor(self):
        p = [NAN] * 8 + [40.6] + [65.0] * 11
        c = [1.5] * 20
        r, _ = self.run1(chart({"Surface Pressure": p, "Btm Prop Conc": c},
                               axes={"Surface Pressure": (100.0, 0.0), "Btm Prop Conc": (500.0, 0.0)}))
        v = r["data"]["Surface Pressure"]
        self.assertTrue(np.allclose(v[:8], 0.0))
        self.assertEqual(v[8], 40.6)

    def test_nothing_is_carried_past_where_every_curve_ends(self):
        p = [60.0] * 9 + [27.7] + [NAN] * 10
        q = [8.0] * 12 + [NAN] * 8
        r, _ = self.run1(chart({"Surface Pressure": p, "Slurry Rate": q},
                               axes={"Surface Pressure": (100.0, 0.0), "Slurry Rate": (16.0, 0.0)}))
        v = r["data"]["Surface Pressure"]
        self.assertTrue(np.isfinite(v[:12]).all() and np.isnan(v[12:]).all())

    def test_off_the_top_stays_blank(self):
        p = [99.5] * 5 + [NAN] * 5 + [99.6] * 5
        r, _ = self.run1(chart({"Surface Pressure": p}, axes={"Surface Pressure": (100.0, 0.0)}))
        self.assertTrue(np.isnan(r["data"]["Surface Pressure"][5:10]).all())

    def test_other_templates_are_untouched(self):
        p = [60.0] * 10 + [NAN] * 5 + [70.0] * 10
        r, notes = self.run1(chart({"Tr Press": p}, source="Liberty chart", axes={"Tr Press": (100.0, 0.0)}))
        self.assertTrue(np.isnan(r["data"]["Tr Press"][10:15]).all())
        self.assertEqual(notes, [])

    def test_an_earlier_deduced_mark_is_kept(self):
        p = [60.0] * 10 + [NAN] * 5 + [70.0] * 10
        r = chart({"Surface Pressure": p}, axes={"Surface Pressure": (100.0, 0.0)})
        prior = np.zeros(25, bool); prior[0] = True
        r["deduced"]["Surface Pressure"] = prior
        self.run1(r)
        self.assertTrue(r["deduced"]["Surface Pressure"][0])
        self.assertEqual(int(r["deduced"]["Surface Pressure"].sum()), 6)


if __name__ == "__main__":
    unittest.main()
