"""The well audit, on defects planted where the corpus produced them.

  python3 -m unittest tests.test_audit

Every shape here is one a client report carried: a channel absent from one
stage (#638), a run pinned to one value (#634's 698.29), a stage number
missing from the ladder because its page died on an implausible duration
(#625), a stage whose clock runs backwards (00495's 3B). And the shapes
that must NOT fire: proppant resting at zero through the pad and flush is
the pen at the floor, not a rule; a 100-kg/m3 hold for six minutes is the
schedule, not a rule; the pad and flush not being drawn is not a loss.

The payload is the Lab's own (localapp._channels_payload's fields), so a
field the Lab renames breaks this before it breaks the audit silently.
"""
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit                                             # noqa: E402

N = 3000


def chan(key, vals, hi, lo=0.0, frame=False):
    ch = {"key": key, "unit": "", "values":
          [None if (v is None or not math.isfinite(v)) else float(v) for v in vals]}
    if frame:                       # the raster templates: axis only at the frame
        ch.update(axisMin=0.0, axisMax=None, frameTop=hi, frameBot=lo)
    else:
        ch.update(axisMin=lo, axisMax=hi)
    return ch


def curves():
    t = np.arange(N)
    press = 40 + 10 * np.sin(t / 300)
    rate = np.clip(8 + 4 * np.sin(t / 400), 0, None)
    # proppant: pad at zero, a stepped ramp, flush at zero
    conc = np.concatenate([np.zeros(600), np.repeat(np.arange(0, 400, 50), 225), np.zeros(600)])
    return press.tolist(), rate.tolist(), conc.tolist()


def stage(label, page, date="2025-04-12", start="08:00:00", dur=50.0, drop=(),
          rule=False, hole=None, spikes=(), bh_off=1.0, wh_holes=(), frame=False):
    press, rate, conc = curves()
    wh = list(conc)
    bh = [v * bh_off for v in conc]
    if rule:
        wh[100:1500] = [698.29] * 1400            # 47% of the stage on one value
    if hole:
        a, z = hole
        press[a:z] = [None] * (z - a)
    for s in spikes:
        press[s:s + 3] = [0.0] * 3
    if wh_holes:
        # Trican does not draw the pad or the flush: the curve starts at the
        # ramp and stops at it, so the drawn span is the ramp alone
        wh[:600] = [None] * 600
        wh[2400:] = [None] * 600
    for a, z in wh_holes:
        wh[a:z] = [None] * (z - a)
    chans = [chan("Tr Press", press, 80, frame=frame), chan("Slurry Rate", rate, 16, frame=frame),
             chan("WH Prop Conc", wh, 800, frame=frame), chan("BH Prop Conc", bh, 800, frame=frame)]
    chans = [c for c in chans if c["key"] not in drop]
    return {"kind": "vector", "meta": {"stage": label, "date": date, "start_time": start,
                                       "duration_min": dur},
            "n": N, "sample_sec": 1.0, "channels": chans,
            "source": "Test chart (raster)", "page": page}


def kinds(res, sev="warn"):
    return {f["kind"] for f in res["findings"] if f["severity"] == sev}


def of(res, kind, sev="warn"):
    return [f for f in res["findings"] if f["kind"] == kind and f["severity"] == sev]


class Clean(unittest.TestCase):
    """Three honest stages produce no warning at all."""

    def test_nothing_fires(self):
        stages = [stage("1", 10, start="08:00:00"), stage("2", 11, start="09:00:00"),
                  stage("3", 12, start="10:00:00")]
        res = audit.audit_stages(stages, [])
        self.assertEqual(kinds(res), set(), [f["evidence"] for f in res["findings"]
                                             if f["severity"] == "warn"])

    def test_pen_at_floor_is_not_a_rule(self):
        # 600 samples at exactly 0 through the pad: the pen at rest
        res = audit.audit_stages([stage("1", 10)], [])
        self.assertEqual(of(res, "flat.rule"), [])

    def test_a_proppant_step_is_information_not_a_warning(self):
        # 225 samples (7.5%) held at 100 kg/m3 — the schedule, not a rule
        res = audit.audit_stages([stage("1", 10)], [])
        self.assertEqual(of(res, "flat.rule"), [])
        self.assertTrue(any(f["kind"] == "flat.rule" for f in res["findings"]
                            if f["severity"] == "info"))

    def test_frame_axis_is_an_axis(self):
        # Trican reports the axis only at the plot frame; it must still count
        res = audit.audit_stages([stage("1", 10, frame=True)], [])
        self.assertEqual(kinds(res), set())


class Planted(unittest.TestCase):

    def test_channel_absent(self):
        stages = [stage("1", 10, drop=("WH Prop Conc",)), stage("2", 11), stage("3", 12)]
        f = of(audit.audit_stages(stages, []), "channel.absent")
        self.assertEqual([(x["stage"], x["channel"]) for x in f], [("1", "WH Prop Conc")])

    def test_rule_read_as_data_and_the_pair_disagrees(self):
        res = audit.audit_stages([stage("3", 12, rule=True)], [])
        flat = of(res, "flat.rule")
        self.assertEqual(len(flat), 1)
        self.assertAlmostEqual(flat[0]["value"], 698.29)
        self.assertEqual(len(of(res, "pair.disagree")), 1)

    def test_one_mid_flight_gap_is_listed_with_its_edges(self):
        res = audit.audit_stages([stage("2", 11, hole=(1200, 1260))], [])
        g = of(res, "gap.missing")
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["span"], [1200, 1260])
        self.assertEqual(g[0]["seconds"], 60.0)

    def test_spikes(self):
        res = audit.audit_stages([stage("5", 14, spikes=(500, 900, 1500))], [])
        sp = of(res, "spike")
        self.assertEqual(len(sp), 1)
        self.assertEqual(sp[0]["count"], 3)
        self.assertLess(sp[0]["largest"], 0)          # downward

    def test_ladder_missing_doubled_failed(self):
        stages = [stage("1", 10), stage("2", 11), stage("4", 13), stage("4", 14)]
        notes = ["p12: Test chart failed — trican-B: implausible stage duration 240455s"]
        res = audit.audit_stages(stages, notes)
        self.assertEqual(of(res, "stage.missing")[0]["stages"], [3])
        self.assertEqual(len(of(res, "stage.doubled")), 1)
        self.assertEqual(of(res, "stage.failed")[0]["page"], 12)

    def test_clock_backwards(self):
        stages = [stage("1", 10, start="08:00:00"), stage("2", 11, start="09:00:00"),
                  stage("3", 12, start="07:30:00")]
        f = of(audit.audit_stages(stages, []), "clock.backwards")
        self.assertEqual([x["stage"] for x in f], ["3"])


class Holds(unittest.TestCase):
    """01350: the reader drops WH Prop Conc wherever the curve holds a level."""

    def setUp(self):
        # every hold of the staircase blanked, each edge on the same level
        holes = [(600 + k * 225 + 20, 600 + k * 225 + 200) for k in range(1, 8)]
        self.stages = [stage("1", 186, wh_holes=holes, frame=True)]
        self.res = audit.audit_stages(self.stages, [])

    def test_sparse_is_measured_against_the_drawn_span(self):
        f = of(self.res, "channel.sparse")
        self.assertEqual([x["channel"] for x in f], ["WH Prop Conc"])
        # 7 × 180 of 1800 drawn samples = 70% — not 42% of the whole stage
        self.assertGreater(f[0]["missing_frac"], 0.6)

    def test_the_hold_shape_is_named(self):
        f = of(self.res, "gap.hold")
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["flat"], f[0]["total"]), (7, 7))

    def test_the_pair_tells(self):
        f = of(self.res, "pair.coverage")
        self.assertEqual([x["channel"] for x in f], ["WH Prop Conc"])

    def test_gaps_roll_up(self):
        listed = of(self.res, "gap.missing")
        self.assertLessEqual(len([g for g in listed if "span" in g]), audit.GAP_LIST_MAX)
        self.assertTrue(any("7 mid-flight gap(s)" in g["evidence"] for g in listed))


if __name__ == "__main__":
    unittest.main()
