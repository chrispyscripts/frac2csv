"""One STEP stage's chart printed again under another stage's number.

00270 prints stage 23's Chemical Analysis plot a second time on Treatment 22's
page (p60 = p62, same values, same 19:46:05 clock) and stage 24's Offset
Analysis page a second time as stage 23's (p63 = p65, 20:23:28). Each copy
took its clock into a stage it does not belong to, and the Lab flagged stages
23 and 24 as starting before the stage before them finished — a fault no
"Fix time" could clear, because both starts were right (#848).

_step_chart_reprints drops such a copy only when nothing else is possible: the same
values as another stage's chart, not its own stage's first chart, a clock
wholly outside its own stage's first chart, and a twin that fits its stage.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import pipeline                                          # noqa: E402

_T = np.arange(20000, dtype=float)


def chart(stage, page, start, n, seed, src="STEP surface chart (raster)"):
    rng = np.random.default_rng(seed)
    return {"type": "series", "source": src, "page": page,
            "meta": {"stage": stage, "date": "2017-06-24", "start_time": start},
            "samples": np.arange(n, dtype=float),
            "data": {"Combined Clean Rate": rng.random(n)},
            "units": {}, "labels": {}, "scales": {}, "frames": {}, "deduced": {}}


def twin(c, stage, page):
    d = chart(stage, page, c["meta"]["start_time"], len(c["samples"]), 0, c["source"])
    d["data"] = {k: v.copy() for k, v in c["data"].items()}
    return d


class StepReprints(unittest.TestCase):
    def setUp(self):
        # the 00270 stage 22/23 shape
        self.t22 = chart("22", 60, "19:11:46", 2010, 1)
        self.t23 = chart("23", 62, "19:45:16", 2269, 2)
        self.c23 = chart("23", 62, "19:46:05", 2251, 3, "STEP chemical chart (raster)")
        self.c22 = twin(self.c23, "22", 60)            # the reprint on p60

    def test_the_copy_outside_its_stage_is_dropped(self):
        res, notes = [self.t22, self.c22, self.t23, self.c23], []
        pipeline._step_chart_reprints(res, notes)
        self.assertNotIn(self.c22, res)
        self.assertIn(self.c23, res, "the copy that fits its stage stays")
        self.assertIn("p60 (filed as stage 22) is stage 23's p62", " ".join(notes))

    def test_a_minute_of_overlap_does_not_save_a_reprint(self):
        # before the hand-over cut stage 22's first chart still runs ~2 min
        # into the copy's window (00270 p60: 100 s of 2251)
        self.t22["samples"] = np.arange(2159, dtype=float)
        self.t22["data"] = {"Combined Clean Rate": np.zeros(2159)}
        res = [self.t22, self.c22, self.t23, self.c23]
        pipeline._step_chart_reprints(res, [])
        self.assertNotIn(self.c22, res)

    def test_both_kept_when_both_fit(self):
        # nothing says which of two fitting copies is the reprint
        c22 = twin(self.c23, "22", 60)
        c22["meta"]["start_time"] = "19:12:00"
        c23 = twin(self.c23, "23", 62)
        c23["meta"]["start_time"] = "19:12:00"
        self.t23["meta"]["start_time"] = "19:11:00"
        res = [self.t22, c22, self.t23, c23]
        pipeline._step_chart_reprints(res, [])
        self.assertEqual(len(res), 4)

    def test_a_stage_never_loses_its_first_chart(self):
        # the copy IS stage 22's only chart: kept, whatever its clock
        res = [self.c22, self.t23, self.c23]
        pipeline._step_chart_reprints(res, [])
        self.assertIn(self.c22, res)

    def test_different_values_are_not_a_reprint(self):
        other = chart("22", 60, "19:46:05", 2251, 9, "STEP chemical chart (raster)")
        res = [self.t22, other, self.t23, self.c23]
        pipeline._step_chart_reprints(res, [])
        self.assertIn(other, res)

    def test_not_step(self):
        for c in (self.t22, self.c22, self.t23, self.c23):
            c["source"] = "canyon chart"
        res = [self.t22, self.c22, self.t23, self.c23]
        pipeline._step_chart_reprints(res, [])
        self.assertEqual(len(res), 4)


if __name__ == "__main__":
    unittest.main()
