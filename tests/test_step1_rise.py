"""STEP 1: a steep rise drawn across several columns is one move, not a spike.

The 2026 STEP books (#799): the pressure goes straight from ~1 to ~30 MPa
across four pixel columns, each inked from the baseline up, and the export
read 0 -> 18 -> 0.7 -> 30 -> 0.8 — a false spike before every rise. A needle
(out and back) still keeps both ends; that is what _keep_excursions is for.

  python3 -m unittest tests.test_step1_rise
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                       # noqa: E402

import step1                                             # noqa: E402

H, W = 300, 40


def _sub_rise():
    m = np.zeros((H, W), bool)
    m[286:290, 0:10] = True                  # the baseline, ~1
    for c, top in zip(range(10, 14), (220, 200, 160, 160)):
        m[top:290, c] = True                 # the thick stroke, baseline up
    m[160:166, 14:40] = True                 # the hold at ~30
    return m


class Rise(unittest.TestCase):

    def test_a_multi_column_rise_never_falls_back(self):
        m = _sub_rise()
        py = np.full(W, np.nan)
        py[0:10] = 287.5                           # run middles, as traced
        py[10:14] = [220.0, 289.0, 289.0, 160.0]   # the envelope's flip-flop
        py[14:] = 162.5
        xs, rows = step1._keep_excursions(m, py)
        seg = rows[(xs >= 9) & (xs <= 15)]
        # rows grow downward: a rise is rows never increasing once it starts
        start = int(np.argmax(seg < 280))
        # never back down by more than a pen's width (the top of the stroke
        # sits a few rows above the hold's middle)
        self.assertTrue(np.all(np.diff(seg[start:]) <= 6.0), seg)
        self.assertLess(seg[start:].max(), 270, seg)            # no return to ~1

    def test_the_upright_trailing_edge_is_not_a_dip(self):
        # 00051 p159: up to ~26, two columns still reading the bottom of the
        # thick upright (~12), then ~22-27 again: the page draws no dip
        m = np.zeros((H, W), bool)
        m[286:290, 0:10] = True
        for c in range(10, 13):
            m[150:290, c] = True                 # the upright
        for c in (13, 14):
            m[150:240, c] = True                 # its trailing edge, top to ~mid
        m[160:166, 15:40] = True                 # carrying on at ~the top
        py = np.full(W, np.nan)
        py[0:10] = 287.5
        py[10:13] = [150.0, 289.0, 150.0]
        py[13:15] = 239.0
        py[15:] = 162.5
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(out[13:15] < 170), out[10:16])

    def test_a_real_dip_after_the_peak_is_kept(self):
        # 00051 p156: up to 30, a drawn dip to 23 held for columns, then on
        m = np.zeros((H, W), bool)
        m[286:290, 0:10] = True
        for c in range(10, 13):
            m[150:290, c] = True
        for c in range(13, 20):
            m[150:200, c] = True                 # the dip, a band 150-200
        m[150:156, 20:40] = True
        py = np.full(W, np.nan)
        py[0:10] = 287.5
        py[10:13] = [150.0, 289.0, 150.0]
        py[13:20] = 199.0                        # held at the dip
        py[20:] = 152.5
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(out[13:20] == 199.0), out[10:21])

    def test_a_repair_never_reads_past_the_curve_nearby(self):
        # 00006 p144: the riser's ink runs on above where the curve goes; its
        # edge read 691 against a step to ~470
        m = np.zeros((H, W), bool)
        m[286:290, 0:10] = True
        for c in range(10, 14):
            m[20:290, c] = True                  # ink far above the step
        m[160:166, 14:40] = True                 # the step's level
        py = np.full(W, np.nan)
        py[0:10] = 287.5
        py[10:14] = [160.0, 289.0, 289.0, 289.0]
        py[14:] = 162.5
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(out[11:14] >= 159.9), out[10:15])   # not up at row 20

    def test_a_real_spike_on_a_fall_is_kept(self):
        # 00048 p139: a needle up during a fall is the page's, and stays
        m = np.zeros((H, W), bool)
        m[150:156, 0:10] = True
        for c in range(10, 14):
            m[150:290, c] = True                 # the fall
        m[40:200, 14] = True                     # a needle up off it
        m[284:290, 15:40] = True
        py = np.full(W, np.nan)
        py[0:10] = 152.5
        py[10:14] = [289.0, 289.0, 289.0, 289.0]
        py[14] = 40.0
        py[15:] = 287.0
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertEqual(out[14], 40.0)

    def test_an_overshoot_at_the_top_of_a_fall_is_kept(self):
        # 00200 p189: the pressure tops out ~30 rows over its hold on the very
        # stroke it falls by; that top is the stage's peak, not a flip back
        m = np.zeros((H, W), bool)
        m[168:173, 0:10] = True                  # the hold
        for c in range(10, 14):
            m[140:290, c] = True                 # up past it, then all the way down
        m[284:290, 14:40] = True
        py = np.full(W, np.nan)
        py[0:10] = 170.0
        py[10:14] = [289.0, 140.0, 289.0, 289.0]
        py[14:] = 287.0
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertEqual(out[11], 140.0)

    def test_a_needle_up_during_a_fall_is_kept(self):
        # 00006 p154: the rate steps down from 12.6 to 10.2 and needles up
        # to 13.4 on the way; the needle's first column reads its top too
        m = np.zeros((H * 2, W), bool)
        m[286:291, 0:10] = True                  # the hold, ~12.6
        for c in range(10, 16):
            m[286:344, c] = True                 # stepping down
        m[257:325, 16] = True                    # the needle, first column
        for c in range(17, 20):
            m[256:487, c] = True                 # the needle, up and down
        m[277:487, 20] = True
        m[377:382, 21:40] = True                 # the new level, ~10.2
        py = np.full(W, np.nan)
        py[0:10] = 288.0
        py[10:16] = 343.0
        py[16] = 257.0
        py[17:20] = 256.0
        py[20] = 307.0
        py[21:] = 379.0
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(out[16:20] <= 257.0), out[15:22])

    def test_a_peak_under_another_series_is_not_a_stray(self):
        # 00163 p207: the pen at the frame top shows as a dot; the columns
        # around it carry only another curve's fringe, lower down. That fringe
        # is not where the move began — the curve's readings just before say so
        m = np.zeros((H, W), bool)
        m[60:65, 0:10] = True                    # the curve, high
        m[248:253, 10:13] = True                 # another series' fringe
        m[2:4, 12] = True                        # the curve's peak, all that shows
        for c in range(13, 16):
            m[10:60, c] = True                   # coming down off it
        m[38:43, 16:40] = True
        py = np.full(W, np.nan)
        py[0:10] = 62.0
        py[12] = 2.5
        py[13:16] = [26.0, 16.0, 30.0]
        py[16:] = 40.0
        out = step1._no_flip_back(m, py, 5.0, 15.0)
        np.testing.assert_array_equal(out, py)

    def test_a_stray_dot_before_a_rise_takes_the_baseline(self):
        # 00049 p136: the two readings before the rise are a dot at row 516,
        # over the baseline at 642-644 that the rise starts from
        m = np.zeros((H * 3, W), bool)
        m[640:645, 0:6] = True                   # the baseline
        m[516, 4:6] = True                       # a stray dot
        for c in range(6, 10):
            m[470:645, c] = True                 # the rise
        m[468:473, 10:40] = True
        py = np.full(W, np.nan)
        py[4:6] = 516.0
        py[6:10] = [644.0, 644.0, 470.0, 470.0]
        py[10:] = 470.0
        out = step1._no_flip_back(m, py, 5.0, 15.0)
        self.assertTrue(np.all(np.abs(out[4:6] - 642.0) <= 1.0), out[3:8])

    @staticmethod
    def _columns(spans, rows=H * 3):
        m = np.zeros((rows, len(spans)), bool)
        for c, (a, b) in enumerate(spans):
            m[a:b + 1, c] = True
        return m

    def test_the_column_after_a_repair_does_not_dip_either(self):
        # 00048 p130: the rise's trailing edge recedes 780, 738, 662, 591 a
        # column after the repaired one; reading it read 20, 21.5, then 7 MPa
        spans = [(785, 789)] * 9 + [(743, 788), (631, 788), (615, 788), (519, 780),
                                    (519, 738), (512, 662), (511, 591)] + [(509, 532)] * 4 \
            + [(521, 534)] * 11                  # the hold
        py = np.r_[np.full(9, 787.0), [788, 631, 788, 738, 738, 631, 588],
                   np.full(4, 509.0), np.full(11, 534.0)]
        out = step1._no_flip_back(self._columns(spans), py, 8.0, 24.0)
        # rows grow downward: from the repaired column on, never back down
        # by more than a stroke-height
        self.assertTrue(np.all(np.diff(out[11:17]) <= 24), out[9:17])

    def test_a_fall_inked_part_way_a_column_still_reads_down(self):
        # 00052 p150: conc falls 320 -> 0, each column inked part way; the
        # column after the repaired one reached 742, not the 782 before it,
        # and must still read low rather than back at the top
        spans = [(276, 282)] * 5 + [(280, 317), (235, 390), (231, 784), (231, 742),
                                    (359, 786), (523, 786)] + [(782, 786)] * 10
        py = np.r_[np.full(5, 282.0), [313, 235, 280, 279, 390, np.nan], np.full(10, 786.0)]
        out = step1._no_flip_back(self._columns(spans), py, 4.0, 12.0)
        self.assertGreater(out[8], 700, out[5:12])

    def test_a_slanted_rise_grows_no_peak(self):
        # 00590 p322: a thick stroke climbing ~40 rows a column; the top of
        # one column's ink runs ahead of the curve, and reading it there made
        # a peak the page doesn't draw (44 MPa, then 40, 38)
        spans = [(553, 558)] * 15 + [(520, 558), (518, 558), (510, 555), (504, 542),
                                     (445, 538), (396, 526), (379, 486), (362, 484),
                                     (324, 460), (278, 419), (273, 382), (265, 352),
                                     (231, 286)] + [(182, 200)] * 3 + [(182, 186)] * 10
        py = np.r_[np.full(15, 556.0), [556, 518, 545, 542, 538, 526, 486, 476, 414, 413,
                                        358, 342, 286], np.full(3, 184.0), np.full(10, 184.0)]
        out = step1._no_flip_back(self._columns(spans), py, 5.0, 15.0)
        # past the columns the first repair reads at their top (col 19 is
        # one, as in 1.11.39): none above both of the next two
        for k in range(20, 27):
            self.assertFalse(out[k] < min(out[k + 1], out[k + 2]) - 15, (k, out[14:30]))

    def test_a_rebound_a_quarter_of_the_way_down_a_fall_goes(self):
        # 00051 p150 (Carmine's Chart 2): the pressure falls from ~72 to ~44;
        # col 76 reads the top of its ink, 26% of the way down, 61.6 MPa
        spans = [(160, 174), (163, 182), (170, 182), (171, 182), (172, 183), (179, 193),
                 (177, 194), (169, 205), (188, 208), (199, 308), (201, 334), (210, 340),
                 (214, 340), (332, 340), (336, 340)] + [(339, 344)] * 10
        py = np.r_[[160, 163, 182, 182, 183, 193, 177, 187, 208, 301, 312, 340, 220, 336.5, 338],
                   np.full(10, 341.5)]
        out = step1._no_flip_back(self._columns(spans), py, 6.0, 18.0)
        self.assertGreater(out[12], 320, out[8:15])

    def test_a_deep_v_after_a_long_climb_keeps_its_bottom(self):
        # 00051 p199: up from the floor to the top, then a real V two thirds
        # of the way back down, and the climb resumes from there (lands at
        # 423, well short of the top at 207)
        spans = [(688, 698)] * 10 + [(600, 698), (450, 650), (300, 500), (210, 350), (205, 260)] \
            + [(205, 230)] * 3 + [(207, 538), (210, 539), (404, 539)] + [(415, 430)] * 10
        py = np.r_[np.full(10, 693.0), [600, 450, 300, 210, 207], np.full(3, 207.0),
                   [538, 539, 539], np.full(10, 423.0)]
        out = step1._no_flip_back(self._columns(spans), py, 6.0, 18.0)
        self.assertTrue(np.all(out[18:21] >= 530), out[15:22])

    def test_a_noisy_band_is_not_a_move_read_from_the_wrong_end(self):
        # 00163 p260's chem conc: a band so thick that a whole stretch is one
        # run of tall columns; a reading at the band's top far from where the
        # band last went deeper is just the band, not a fall-back
        spans = [(296, 304)] * 7 + [(362, 370)] * 3 + [(352, 521)] * 2 + [(352, 549)] \
            + [(352, 521)] * 48 + [(307, 532)] * 3 + [(298, 655)] * 17 + [(650, 658)] * 10
        py = np.r_[np.full(7, 300.0), np.full(3, 366.0), [521, 521, 549], np.full(48, 521.0),
                   np.full(3, 307.0),
                   np.full(17, 655.0), np.full(10, 654.0)]
        out = step1._no_flip_back(self._columns(spans), py, 9.0, 27.0)
        self.assertTrue(np.all(out[61:64] == 307.0), out[58:66])

    def test_a_trace_opening_mid_rise_at_the_frame_edge(self):
        # Carmine's Chart 2 (00051 p150): the pressure enters at the frame's
        # left edge from the floor and climbs; the opening read 18, 16, 1, 13,
        # 13, 13, 21, 28, 16, 39, 39, 31 MPa. Col 2 read the floor end of
        # the entry bar, cols 1-5 the foot of a block whose top holds the
        # entry level, col 8 the foot of its stroke, cols 9-10 a fleck where
        # two gridlines cross. It climbs, and never drops back.
        runs = [[(465, 472), (477, 492), (503, 568)], [(457, 484), (488, 568)], [(458, 568)],
                [(457, 500), (502, 502), (505, 520)], [(457, 497)], [(458, 498)],
                [(441, 450), (457, 469), (472, 498)], [(413, 416), (419, 482), (489, 492)],
                [(409, 480), (489, 489)], [(347, 348), (381, 440)],
                [(347, 348), (381, 381), (383, 440)], [(370, 392), (394, 395)], [(367, 392)],
                [(363, 376)], [(363, 376)], [(359, 366)]] + [[(350, 356)]] * 10
        m = np.zeros((600, len(runs)), bool)
        for c, rs in enumerate(runs):
            for a, b in rs:
                m[a:b + 1, c] = True
        py = np.r_[[468.5, 484, 568, 502, 497, 498, 450, 414.5, 480, 347.5, 347.5, 395, 392,
                    376, 376, 362.5], np.full(10, 353.0)]
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        for k in range(1, 13):                   # rows grow downward
            self.assertLessEqual(out[k], np.min(out[:k]) + 18, (k, out[:13]))
        self.assertTrue(np.all((out[9:11] > 375) & (out[9:11] <= 400)), out[:12])

    def test_a_sag_drawn_after_the_entry_is_kept(self):
        # 00052 p150: in at the frame's edge to 485, then the ink's top edge
        # itself drops (527 at col 6) and the climb sets off from 574: a sag
        # the page draws. The floor reads at cols 2-3 still go.
        runs = [[(485, 530)]] * 2 + [[(485, 722)]] * 2 + [[(487, 574)]] * 2 + [[(527, 574)]] * 2 \
            + [[(428, 570)], [(391, 564)], [(313, 534)], [(313, 518)], [(312, 406)]] + [[(302, 310)]] * 10
        m = np.zeros((800, len(runs)), bool)
        for c, rs in enumerate(runs):
            for a, b in rs:
                m[a:b + 1, c] = True
        py = np.r_[[485.5, 485.5, 722, 722, 574, 574, 574, 574, 563, 564, 534, 518, 406],
                   np.full(10, 306.0)]
        out = step1._no_flip_back(m, py, 4.0, 12.0)
        self.assertTrue(np.all(out[2:4] < 600), out[:13])         # not the floor
        self.assertTrue(np.all(out[4:8] >= 560), out[:13])        # the sag stays

    def test_a_long_thick_climb_read_front_and_foot_is_monotone(self):
        # Stage 6 (00051 p155): after a short hold the pressure climbs ~350
        # rows through a thick stroke; the columns read its front and its
        # foot by turns: 523, 397, 482, 293, 463, 375, 361, 263, 262, 168
        runs = [[(712, 717)]] * 7 + [
            [(541, 559), (563, 569), (571, 572), (575, 715)], [(502, 502), (513, 715)],
            [(497, 713)], [(497, 695)], [(498, 523)], [(498, 525)], [(488, 489), (494, 523)],
            [(473, 523)], [(397, 398), (401, 415), (418, 523)], [(392, 482), (486, 520)],
            [(293, 293), (304, 471)], [(280, 287), (289, 463)], [(216, 375), (379, 379)],
            [(206, 361)], [(182, 263)], [(175, 262)], [(168, 168), (170, 205)], [(169, 203)],
            [(170, 205), (207, 207)], [(171, 207)], [(178, 206)], [(178, 204), (207, 207)],
            [(177, 191), (200, 200)], [(176, 189), (191, 191)]] + [[(176, 185)]] * 10
        m = np.zeros((720, len(runs)), bool)
        for c, rs in enumerate(runs):
            for a, b in rs:
                m[a:b + 1, c] = True
        py = np.r_[np.full(7, np.nan), [559, 502, 713, 695, 523, 525, 488.5, 523, 397.5, 482, 293,
                                        463, 375, 361, 263, 262, 168, 169, 170, 171, 206, 204,
                                        200, 176], np.full(10, 180.0)]
        out = step1._no_flip_back(m, py, 6.0, 18.0)
        self.assertTrue(np.all(np.diff(out[13:24]) <= 18), out[11:25])   # never back down

    def test_a_notch_just_after_a_rise_is_kept(self):
        # 00048 p142: up to 515, a notch drawn at ~566 (its lower edge holds
        # 582, 566, 566), then on up to ~434
        spans = [(784, 788)] * 10 + [(759, 786), (743, 786), (561, 786), (515, 784),
                                     (513, 742), (513, 731), (513, 582), (513, 566),
                                     (536, 566), (517, 566), (451, 563)] + [(428, 440)] * 10
        py = np.r_[np.full(10, 786.0), [786, 786, 563, 515, 742, 715, 572, 566, 566, 517, 452],
                   np.full(10, 434.0)]
        out = step1._no_flip_back(self._columns(spans), py, 5.0, 15.0)
        self.assertTrue(np.all(out[16:19] >= 560), out[13:21])

    def test_a_needle_keeps_its_depth(self):
        m = np.zeros((H, W), bool)
        m[160:166, :] = True                 # a level line
        m[160:290, 20] = True                # one column down to the floor and back
        py = np.full(W, 162.5)
        py[20] = 224.5                       # the run's middle, as traced
        xs, rows = step1._keep_excursions(m, py)
        self.assertGreaterEqual(rows.max(), 285)    # the needle's tip survives


SPUD = os.path.expanduser("~/frac-data/BCER-Frac-Spud-2026")


def _spud(num):
    import glob
    hits = glob.glob(os.path.join(SPUD, f"{num}-*.pdf"))
    return hits[0] if hits else None


def _pressure_columns(pdf, pno):
    """The surface pressure's column readings after the flip-back repair."""
    import fitz
    got = []
    real = step1._no_flip_back

    def keep(sub, py, med, tall, **kw):
        out = real(sub, py, med, tall, **kw)
        got.append(out)
        return out
    step1._no_flip_back = keep
    try:
        step1.extract_page(fitz.open(pdf)[pno - 1])
    finally:
        step1._no_flip_back = real
    return got[0]


@unittest.skipUnless(_spud("00051") and _spud("00048"), "the 2026 STEP filings are not on this machine")
class OnThePage(unittest.TestCase):

    def test_stage_6_climbs_without_turning_back(self):
        # Carmine's Stage 6 (00051 p155): front and foot by turns in v1.11.42
        out = _pressure_columns(_spud("00051"), 155)
        self.assertTrue(np.all(np.diff(out[13:24]) <= 18), out[11:25])

    def test_00048_p142_keeps_its_v(self):
        # a V drawn after the climb, its bottom at row 540 in col 31
        out = _pressure_columns(_spud("00048"), 142)
        self.assertGreater(out[31], 530, out[28:34])


ARC_00100 = glob.glob("/Volumes/CnC-2TB-ssd/AER-Frac-*/00100-103141106404W600_0489643_COMP.pdf")


@unittest.skipUnless(ARC_00100, "the CnC drive is not mounted")
class SpeckAfterAClimb(unittest.TestCase):

    def test_00100_p173_reads_the_stroke_not_the_orange_pixel(self):
        # cols 281-282 read one pixel of the orange curve at row 680 under the
        # red stroke at 80-235, just after a climb from row 746 to 235
        out = _pressure_columns(ARC_00100[0], 173)
        fin = [v for v in out[268:285] if np.isfinite(v)]
        self.assertTrue(np.all(np.diff(fin) <= 0), out[268:285])


if __name__ == "__main__":
    unittest.main()
