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
        w = of(res, "gap.missing")                    # one warning for the channel …
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["count"], 1)
        g = [x for x in of(res, "gap.missing", "info") if "span" in x]   # … the gap beneath it
        self.assertEqual(g[0]["span"], [1200, 1260])
        self.assertEqual(g[0]["seconds"], 60.0)

    def test_pressure_spikes_at_the_stage_edges_are_information(self):
        # 00026: a ball seating in the first minutes, a shutdown in the last —
        # the page draws them; the sweep's warnings are for the mask's errors
        res = audit.audit_stages([stage("6", 15, spikes=(60, 120, N - 90))], [])
        self.assertEqual(of(res, "spike"), [])
        info = [f for f in of(res, "spike", "info") if f["channel"] == "Tr Press"]
        self.assertTrue(info)
        self.assertIn("transients at the stage's edges", info[0]["action"])

    def test_a_mid_stage_spike_still_warns_even_with_one_at_the_edge(self):
        res = audit.audit_stages([stage("7", 16, spikes=(60, 900, 1500))], [])
        self.assertTrue([f for f in of(res, "spike") if f["channel"] == "Tr Press"])

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

    def test_a_window_a_few_minutes_wide_of_its_stage_is_not_an_overlap(self):
        # 00015: 94-minute chart windows over 88-minute stages, back to back
        stages = [stage("1", 10, start="15:00:00", dur=94.0), stage("2", 11, start="16:29:00", dur=70.0),
                  stage("3", 12, start="17:32:00", dur=65.0)]
        self.assertEqual(of(audit.audit_stages(stages, []), "clock.overlap"), [])
        # 01433 stage 61: 19 minutes inside a 37-minute stage 60 — the Lab flags it, so does this
        stages = [stage("60", 213, start="06:03:00", dur=140.0), stage("61", 214, start="08:04:00", dur=37.0)]
        self.assertEqual(len(of(audit.audit_stages(stages, []), "clock.overlap")), 1)

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
        # under the channel's own warning the gaps are evidence: info-level
        listed = of(self.res, "gap.missing", "info")
        self.assertLessEqual(len([g for g in listed if "span" in g]), audit.GAP_LIST_MAX)
        self.assertTrue(any("7 mid-flight gap(s)" in g["evidence"] for g in listed))


class FromTheAcceptanceRun(unittest.TestCase):
    """What the first run over Carmine's week taught the detectors."""

    def test_two_templates_one_stage_is_the_layout(self):
        # STEP: a surface chart and a chemical chart per stage, same label,
        # same clock — 01316 gave 46 stage.doubled and 46 clock findings
        stages = []
        for k in (1, 2, 3):
            a = stage(str(k), 10 + k, start=f"{7 + k:02d}:00:00")
            b = stage(str(k), 10 + k, start=f"{7 + k:02d}:00:00")
            b["source"] = "Test chemical chart (raster)"
            stages += [a, b]
        res = audit.audit_stages(stages, [])
        self.assertEqual(of(res, "stage.doubled"), [])
        self.assertEqual(kinds(res) & {"clock.overlap", "clock.backwards"}, set())

    def test_a_missing_stage_is_named_by_its_failed_page(self):
        stages = [stage("1", 10), stage("2", 11), stage("4", 13), stage("5", 14), stage("7", 16)]
        notes = ["p12: Test chart failed — trican-B: implausible stage duration 48466s"]
        res = audit.audit_stages(stages, notes)
        failed = of(res, "stage.failed")[0]
        self.assertEqual(failed["stage_linked"], 3)
        miss = of(res, "stage.missing")[0]
        self.assertEqual(miss["stages"], [3, 6])
        self.assertEqual(miss["linked"], {3: 12})
        self.assertIn("6 has no page at all", miss["evidence"])

    def test_no_axis_spike_is_information_unless_it_plunges(self):
        press, _, _ = curves()
        small = list(press)
        for k in (500, 900, 1500):
            small[k:k + 3] = [press[k] + 4.0] * 3      # +4 on a 30..50 curve
        st = stage("1", 10)
        st["channels"] = [{"key": "Tr Press", "unit": "", "axisMin": 0.0, "axisMax": None,
                           "values": small}]
        res = audit.audit_stages([st], [])
        self.assertEqual(of(res, "spike"), [])
        self.assertTrue(of(res, "spike", "info"))
        plunge = list(press)
        for k in (500, 900, 1500):
            plunge[k:k + 3] = [0.0] * 3                # #629: down to nothing and back
        st["channels"][0]["values"] = plunge
        res = audit.audit_stages([st], [])
        self.assertEqual(len(of(res, "spike")), 1)

    def test_spikes_at_one_second_on_three_channels_are_one_defect(self):
        # sample 1500 sits on the 200 kg/m3 step, so proppant has somewhere
        # to plunge from; at 800 it is still 0 and a spike to 0 is no spike
        st = stage("7", 37, spikes=(1500,))
        for c in st["channels"]:
            if c["key"] in ("Slurry Rate", "BH Prop Conc"):
                c["values"][1500:1503] = [0.0] * 3
        res = audit.audit_stages([st], [])
        f = of(res, "spike.aligned")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["moments"], [1500])

    def test_gap_lines_are_evidence_under_a_channel_warning(self):
        holes = [(600 + k * 225 + 20, 600 + k * 225 + 200) for k in range(1, 8)]
        res = audit.audit_stages([stage("1", 186, wh_holes=holes, frame=True)], [])
        self.assertTrue(of(res, "channel.sparse"))
        self.assertEqual(of(res, "gap.missing"), [])          # no gap WARNs …
        self.assertTrue(of(res, "gap.missing", "info"))       # … they are info


class Clocks(unittest.TestCase):
    """#639: 00015 prints "Clock Time (hour:min)" over every chart and every
    stage exported 00:00:00. Without the page that blank is information —
    00020's charts plot elapsed minutes and have no clock to read. With the
    page, it is a warning, and 0 of N is one finding about the template."""

    def unclocked(self, n, printed):
        out = []
        for k in range(1, n + 1):
            st = stage(str(k), 30 + 2 * k, date="", start="00:00:00")
            if printed:
                st["clock_printed"] = "18:30–19:32"
            out.append(st)
        return out

    def test_no_clock_and_no_page_is_information(self):
        res = audit.audit_stages(self.unclocked(4, printed=False), [])
        self.assertEqual(of(res, "clock.absent"), [])
        self.assertEqual(len(of(res, "clock.absent", "info")), 4)
        none = of(res, "clock.none")
        self.assertEqual(len(none), 1)
        self.assertEqual(none[0]["printed"], 0)

    def test_a_printed_clock_the_reader_missed_is_a_warning(self):
        res = audit.audit_stages(self.unclocked(4, printed=True), [])
        self.assertEqual(len(of(res, "clock.absent")), 4)
        self.assertIn("18:30–19:32", of(res, "clock.absent")[0]["evidence"])
        self.assertEqual(of(res, "clock.none")[0]["printed"], 4)

    def test_one_unclocked_stage_among_clocked_ones_is_not_a_template_fault(self):
        stages = [stage("1", 10, start="08:00:00"), stage("2", 11, start="09:00:00"),
                  stage("3", 12, date="", start="00:00:00")]
        res = audit.audit_stages(stages, [])
        self.assertEqual(of(res, "clock.none"), [])

    def test_midnight_with_a_date_is_a_clock(self):
        stages = [stage("3", 39, date="2015-07-06", start="17:32:00"),
                  stage("4", 41, date="2015-07-07", start="00:00:00"),
                  stage("5", 43, date="2015-07-07", start="08:27:00")]
        res = audit.audit_stages(stages, [])
        self.assertEqual(kinds(res) & {"clock.absent", "clock.none", "clock.in-table"}, set())
        self.assertEqual(of(res, "clock.absent", "info"), [])

    def test_clock_hint_reads_the_page(self):
        self.assertEqual(audit._clock_hint("Clock Time (hour:min)\n18:30 18:40 18:50 19:32\nElapsed"), "18:30–19:32")
        self.assertEqual(audit._clock_hint("Elapsed Time (min)\n210.0 220.0 230.0"), "")
        self.assertEqual(audit._clock_hint("Job Date: 2015-07-19\nStart 08:15"), "")   # one token is not an axis

    def test_a_start_printed_in_the_stage_table_is_a_join_never_made(self):
        # 00015: the summary table has a start for every stage, no chart has one
        table = {"title": "well — per-stage engineering data (Trican)", "kind": "summary",
                 "columns": ["UWI", "stage", "start", "finish", "total_time_min"],
                 "rows": [["x", "1", "03:00", "04:29", "88.5"], ["x", "2", "04:29", "05:32", "63.1"],
                          ["x", "3", "05:32", "06:31", "59.7"], ["x", "4", "12:00", "01:00", "60.2"]]}
        res = audit.audit_stages(self.unclocked(4, printed=False), [], [table])
        f = of(res, "clock.in-table")
        self.assertEqual([x["stage"] for x in f], ["1", "2", "3", "4"])
        self.assertIn("05:32", f[2]["evidence"])
        self.assertEqual(of(res, "clock.absent", "info"), [])         # in-table replaces absent
        none = of(res, "clock.none")[0]
        self.assertEqual(none["in_table"], 4)
        self.assertIn("AM/PM", none["action"])

    def test_a_start_date_column_is_not_a_start_time(self):
        table = {"title": "t", "kind": "summary", "columns": ["Stage", "Start Date", "Max Press"],
                 "rows": [["1", "2025-02-15", "60"]]}
        self.assertEqual(audit.table_clocks([table]), {})
        self.assertEqual(audit.table_clocks([{"columns": ["stage", "start"], "rows": [["7", "3:05 PM"], ["8", "-"]]}]),
                         {7: "3:05 PM"})

    def test_unlabelled_overview_charts_are_not_doubles(self):
        stages = [stage("1", 10), stage("2", 11), stage("", 57, dur=272), stage("", 59, dur=432)]
        res = audit.audit_stages(stages, [])
        self.assertEqual(of(res, "stage.doubled"), [])
        self.assertEqual(of(res, "stage.unlabelled", "info")[0]["evidence"][:1], "2")



class FromTheOctoberScan(unittest.TestCase):
    """The 95-file scan of 00184-00278 (2026-10-27): the checks it needed."""

    TABLE = {"title": "Daily Stage Summary", "columns": ["Stage", "Top", "Date", "Start Time", "Slurry"],
             "rows": [["1", "3500", "2017-04-01", "08:00", "120"], ["2", "3450", None, None, None],
                      ["3", "3400", "2017-04-01", "10:00", "118"], ["4", "3350", "2017-04-01", "11:00", "121"],
                      ["5", "3300", "2017-04-01", "12:00", "119"]]}

    def test_a_gap_the_table_leaves_blank_was_not_pumped(self):
        # 00185: stages blank in the Daily Stage Summary have no chart, rightly
        stages = [stage("1", 10), stage("3", 12)]
        res = audit.audit_stages(stages, [], [self.TABLE])
        self.assertEqual(of(res, "stage.not-pumped", "info")[0]["stages"], [2])
        # ...while the table's 4 and 5, past the last chart, are missing (00271)
        self.assertEqual(of(res, "stage.missing")[0]["stages"], [4, 5])
        self.assertIn("Daily Stage Summary", of(res, "stage.missing")[0]["evidence"])

    def test_without_a_table_the_ladder_is_as_before(self):
        res = audit.audit_stages([stage("1", 10), stage("3", 12)], [])
        self.assertEqual(of(res, "stage.missing")[0]["stages"], [2])
        self.assertEqual(of(res, "stage.not-pumped", "info"), [])

    def test_every_chart_one_stage_is_a_number_read_once(self):
        # 00232: "Interval: 1" on the first page, the bare number after
        stages = [stage("1", 10 + k, start=f"{8 + k:02d}:00:00") for k in range(5)]
        f = of(audit.audit_stages(stages, []), "stage.single")
        self.assertEqual(len(f), 1)
        self.assertIn("all 5", f[0]["evidence"])
        # a one-stage job draws a chart or two, not five
        self.assertEqual(of(audit.audit_stages(stages[:2], []), "stage.single"), [])
        # and a well with its stages numbered says nothing
        ok = [stage(str(k), 10 + k, start=f"{8 + k:02d}:00:00") for k in range(1, 6)]
        self.assertEqual(of(audit.audit_stages(ok, []), "stage.single"), [])

    def test_stage_question_mark_is_a_warning_at_a_stages_length(self):
        # 00278: 60 stage-length charts with no number; an overview stays info
        stages = [stage("1", 10), stage("2", 11), stage("", 12), stage("", 13, dur=400)]
        res = audit.audit_stages(stages, [])
        self.assertEqual(of(res, "stage.unknown")[0]["pages"], [12])
        self.assertEqual(len(of(res, "stage.unlabelled", "info")), 1)

    def test_an_overlap_says_why_when_the_numbers_show_it(self):
        # a date a day off: stage 2 dated the day before
        stages = [stage("1", 10, date="2017-04-02", start="08:00:00", dur=60),
                  stage("2", 11, date="2017-04-01", start="09:10:00", dur=60)]
        f = of(audit.audit_stages(stages, []), "clock.backwards")
        self.assertEqual(len(f), 1)
        stages = [stage("1", 10, date="2017-04-02", start="08:00:00", dur=1500),
                  stage("2", 11, date="2017-04-02", start="09:10:00", dur=60)]
        f = of(audit.audit_stages(stages, []), "clock.overlap")
        self.assertIn("a date 1 day off", f[0]["cause"])
        # the table prints both starts and stage 1's chart sits 40 min early
        table = {"columns": ["Stage", "Start Time"], "rows": [["1", "08:40"], ["2", "09:10"]]}
        stages = [stage("1", 10, start="08:00:00", dur=100), stage("2", 11, start="09:10:00", dur=60)]
        f = of(audit.audit_stages(stages, [], [table]), "clock.overlap")
        self.assertIn("stage 1's chart", f[0]["cause"])
        # both where the table puts them: the report's own times overlap
        table = {"columns": ["Stage", "Start Time"], "rows": [["1", "08:00"], ["2", "09:10"]]}
        f = of(audit.audit_stages(stages, [], [table]), "clock.overlap")
        self.assertIn("the report's own times", f[0]["cause"])


def offset(label, page, wells=("A", "B", "C"), **kw):
    """STEP's offset-well plot: same source tag and stage as the treatment
    plot beside it, treating pressure plus one pen per offset well"""
    st = stage(label, page, **kw)
    press = st["channels"][0]["values"]
    st["channels"] = [st["channels"][0]] + [chan(f"{w} Well Offset Pressure", press, 80)
                                            for w in wells]
    return st


class TwoChartsAStage(unittest.TestCase):
    """00241 / 00243: a treatment plot and an offset-well plot for every
    stage, both "STEP surface chart". Compared as one template, every offset
    pen was absent from every treatment chart and every stage was doubled."""

    def well(self):
        out = []
        for k in range(1, 6):
            out += [stage(str(k), 2 * k + 10, start=f"{7 + k:02d}:00:00"),
                    offset(str(k), 2 * k + 11, start=f"{7 + k:02d}:00:00")]
        return out

    def test_the_two_plots_are_two_kinds(self):
        res = audit.audit_stages(self.well(), [])
        self.assertEqual(of(res, "channel.absent"), [])
        self.assertEqual(of(res, "stage.doubled"), [])

    def test_a_pen_lost_on_one_plot_is_still_found(self):
        sts = self.well()
        sts[4] = stage("3", 16, start="10:00:00", drop=("Slurry Rate",))
        sts[7] = offset("4", 19, wells=("A", "B"), start="11:00:00")
        f = of(audit.audit_stages(sts, []), "channel.absent")
        self.assertEqual(sorted((x["stage"], x["channel"]) for x in f),
                         [("3", "Slurry Rate"), ("4", "C Well Offset Pressure")])

    def test_a_stage_with_one_plot_joins_its_own_kind(self):
        sts = self.well()
        del sts[4]                            # stage 3 printed its offset plot only
        res = audit.audit_stages(sts, [])
        self.assertEqual(of(res, "channel.absent"), [])

    def test_charts_that_all_say_midnight_have_no_clock(self):
        # 00278: dated, 00:00:00, no clock printed — 54 "overlaps" before
        sts = [stage(str(k), 10 + k, date="2017-02-12", start="00:00:00", dur=70)
               for k in range(1, 6)]
        res = audit.audit_stages(sts, [])
        self.assertEqual(of(res, "clock.overlap"), [])
        self.assertEqual(of(res, "clock.backwards"), [])
        # one chart at midnight among clocked ones is a midnight, and compared
        sts = [stage("1", 10, start="23:00:00", dur=90), stage("2", 11, date="2025-04-13",
                                                                start="00:00:00", dur=50)]
        self.assertEqual(len(of(audit.audit_stages(sts, []), "clock.overlap")), 1)

    def test_a_third_chart_of_a_stage_is_still_doubled(self):
        sts = self.well() + [stage("2", 40, start="09:00:00")]
        f = of(audit.audit_stages(sts, []), "stage.doubled")
        self.assertEqual(len(f), 1)
        self.assertIn("'2'", f[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
