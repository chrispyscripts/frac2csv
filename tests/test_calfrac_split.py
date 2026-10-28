"""Cutting a CalFrac "Zones N-M" page into zones, and dating it.

Three faults, all found scanning v1.11.53 output on the 00184-00278 batch:

  * _match_cuts slid its clock origin the WRONG way. A target is
    (printed start - t0); boundaries landing LATER than their targets mean
    the page opened EARLIER. Adding the offset instead of subtracting it
    doubled the error each pass (3.6, 7.1, 14.2 min on 00194 p98), the match
    failed, and the page fell through to a noisier candidate set that
    labelled every zone one early and gave zone 19 zone 20's treatment.
  * the LAST zone of a page ran to the end of the time axis, which MView
    draws past the data: 00194's zone 19 ran 176 min against ~65 for its
    neighbours, 00188's zone 28 141 min, every channel 26-49% filled.
  * a sheet's Job Date printed as a RANGE ("08/20/2017 - 08/22/2017") names
    the job's first day — a floor nothing on the sheet ran before. A single
    date does not (00218's Mar 1 sheet opens with a zone begun Feb 28).

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calfrac_progress as cp                            # noqa: E402

# 00194 p98 "Zones 3-19": the printed Start Times (minutes since midnight)
# and the 19 concentration breaks (minutes into the page) the page offers at
# the lowest threshold. Sixteen of them are zone boundaries; 777, 852 and
# 1061 are dips inside a zone. The page opened at 01:28-01:30.
P98_PRINTED = {4: 196, 5: 288, 6: 383, 7: 470, 8: 548, 9: 621, 10: 698,
               12: 883, 13: 967, 14: 1034, 15: 1102, 16: 1180, 17: 1248,
               18: 1315, 19: 1381}
P98_CANDS = [108.0, 199.0, 299.0, 380.0, 457.0, 531.0, 608.0, 698.0, 777.0,
             793.0, 852.0, 876.0, 944.0, 1011.0, 1061.0, 1091.0, 1158.0,
             1224.0, 1291.0]


class OriginSlide(unittest.TestCase):
    def test_00194_p98_matches_sixteen_boundaries(self):
        got = cp._match_cuts(P98_CANDS, list(range(3, 20)), P98_PRINTED, 1400.0)
        self.assertIsNotNone(got)
        cuts, t0 = got
        self.assertEqual(cuts, [108.0, 199.0, 299.0, 380.0, 457.0, 531.0,
                                608.0, 698.0, 793.0, 876.0, 944.0, 1011.0,
                                1091.0, 1158.0, 1224.0, 1291.0])
        # the page opened at about 01:30, not the 02:59 the noisy set implied
        self.assertAlmostEqual(t0, 90.0, delta=5.0)

    def test_boundaries_after_their_printed_starts_pull_the_origin_back(self):
        # The pumps come back 3-12 min after the start the sheet prints, and
        # two dips inside zones (150, 280) are on offer as well. The first
        # guess is a few minutes out; sliding it the wrong way failed this
        # page outright.
        printed = {2: 600, 3: 663, 4: 730, 5: 792, 6: 860}
        cands = [63.0, 132.0, 150.0, 202.0, 255.0, 280.0, 330.0]
        got = cp._match_cuts(cands, [1, 2, 3, 4, 5, 6], printed, 400.0)
        self.assertIsNotNone(got)
        cuts, t0 = got
        self.assertEqual(cuts, [63.0, 132.0, 202.0, 255.0, 330.0])
        self.assertAlmostEqual(t0, 531.0, delta=1.0)


class PauseEdges(unittest.TestCase):
    """A printed start is measured against the pause, not its middle."""

    def test_00256_a_long_pause_still_matches(self):
        # zones 1-4: zone 3 stops 12:02, zone 4 starts 13:10 after a 68-min
        # pause whose middle (12:36) is 34 min from the printed start
        printed = {2: 121, 3: 260, 4: 428}
        cands = [120.0, 263.0, 394.0]
        spans = [(118.0, 122.0), (261.0, 265.0), (360.0, 428.0)]
        self.assertIsNone(cp._match_cuts(cands, [1, 2, 3, 4], printed, 600.0))
        got = cp._match_cuts(cands, [1, 2, 3, 4], printed, 600.0, spans)
        self.assertIsNotNone(got)
        self.assertEqual(got[0][:2], cands[:2])
        # and the long pause is cut at zone 4's printed start, not its middle
        self.assertAlmostEqual(got[0][2], 428.0, delta=2.0)

    def test_a_long_pause_is_cut_at_the_printed_start(self):
        # 00227: two hours' wait before zone 4; its middle is an hour early
        printed = {2: 67, 3: 142, 4: 318}
        cands = [67.0, 142.0, 256.0]
        spans = [(65.0, 69.0), (140.0, 144.0), (195.0, 318.0)]
        got = cp._match_cuts(cands, [1, 2, 3, 4], printed, 600.0, spans)
        self.assertIsNotNone(got)
        self.assertEqual(got[0][:2], [67.0, 142.0])     # short: the middle
        self.assertAlmostEqual(got[0][2], 318.0, delta=1.0)

    def test_the_distance_to_a_pause(self):
        self.assertEqual(cp._gap_dist((10.0, 20.0), 15.0), 0.0)
        self.assertEqual(cp._gap_dist((10.0, 20.0), 25.0), 5.0)
        self.assertEqual(cp._gap_dist((10.0, 20.0), 4.0), 6.0)


class TimesForRange(unittest.TestCase):
    def test_00277_the_sheet_that_columns_this_page_wins(self):
        # p42: the Dec 9 attempt, zones 1-5; p43: the Jan job from zone 5
        times = {41: {1: {"start": "1:00"}, 5: {"start": "4:32"}},
                 42: {5: {"start": "23:35"}, 6: {"start": "0:49"},
                      7: {"start": "1:47"}}}
        self.assertEqual(cp.times_for_range(times, 45, 1, 5)[5]["start"],
                         "4:32")
        self.assertEqual(cp.times_for_range(times, 49, 5, 23)[5]["start"],
                         "23:35")
        # page order still wins between equals, as times_before always did
        self.assertEqual(cp.times_before(times, 45)[5]["start"], "23:35")


class LastZone(unittest.TestCase):
    def test_ends_where_the_data_does(self):
        n = 1000
        rate = np.full(n, np.nan)
        rate[:900] = 5.0
        bounds = [(0, 400), (400, 1000)]
        self.assertEqual(cp.trim_last_zone(bounds, {"Slurry Rate": rate}),
                         [(0, 400), (400, 900)])

    def test_a_channel_still_recording_keeps_it_open(self):
        n = 1000
        rate = np.full(n, np.nan)
        rate[:700] = 5.0
        press = np.full(n, np.nan)
        press[:950] = 20.0          # shut-in pressure after the pumps stop
        bounds = [(0, 400), (400, 1000)]
        self.assertEqual(cp.trim_last_zone(bounds, {"Slurry Rate": rate,
                                                    "Tr Press": press}),
                         [(0, 400), (400, 950)])

    def test_inner_cuts_and_a_full_page_are_untouched(self):
        rate = np.full(1000, 5.0)
        bounds = [(0, 400), (400, 1000)]
        self.assertEqual(cp.trim_last_zone(bounds, {"Slurry Rate": rate}),
                         bounds)

    def test_a_last_zone_with_no_data_at_all_is_left_alone(self):
        rate = np.full(1000, np.nan)
        rate[:300] = 5.0
        bounds = [(0, 400), (400, 1000)]
        self.assertEqual(cp.trim_last_zone(bounds, {"Slurry Rate": rate}),
                         bounds)


class LentBackCuts(unittest.TestCase):
    """00275: the captioned "Zones 9-32" Surface sheet would not split; its
    Bottom Hole twin did, and lends the cuts back."""

    def setUp(self):
        self._zr = cp.zone_range
        cp.zone_range = lambda page: (9, 11)

    def tearDown(self):
        cp.zone_range = self._zr

    def test_the_captioned_page_is_cut_on_its_twins_cuts(self):
        import frac_core as fc
        import pipeline
        n = 3000
        samples = np.arange(n, dtype=float)
        data = {"Tr Press": np.full(n, 50.0)}       # nothing to split on
        lend = {"range": (9, 11), "zones": [9, 10, 11], "anchor": (600.0, 3),
                "cuts": [(0.0, 0.3), (0.3, 0.7), (0.7, 1.0)]}
        parts = pipeline._split_progress(
            None, fc.PageMeta(), samples, data, {}, 1.0, [], 40, [None],
            lend=lend)
        self.assertEqual([p[0]["stage"] for p in parts], ["9", "10", "11"])
        self.assertEqual([len(p[1]) for p in parts], [900, 1200, 900])
        self.assertEqual(parts[1][0]["start_time"], "10:15:00")


class JobDate(unittest.TestCase):
    def _v(self, text):
        d = cp._job_date_value(text)
        return (str(d), d.ranged) if d else None

    def test_slash_ranges(self):
        self.assertEqual(self._v("08/20/2017 - 08/22/2017"),
                         ("2017-08-20", True))
        self.assertEqual(self._v("08/12/2017 - 8/13/2017  8:00:00 AM"),
                         ("2017-08-12", True))

    def test_a_range_whose_end_is_not_a_date_is_still_a_range(self):
        # 00190 p86, exactly
        self.assertEqual(self._v("08/17/2017 - 08/18-2018"),
                         ("2017-08-17", True))

    def test_word_ranges(self):
        self.assertEqual(self._v("Aug 18-19, 2017"), ("2017-08-18", True))
        self.assertEqual(self._v("Aug. 04 - 05, 2017"), ("2017-08-04", True))

    def test_single_dates_are_not_ranges(self):
        self.assertEqual(self._v("Aug 25, 2017"), ("2017-08-25", False))
        self.assertEqual(self._v("Mar 01, 2017"), ("2017-03-01", False))
        self.assertEqual(self._v("8/25/2017"), ("2017-08-25", False))

    def test_it_is_still_a_plain_date_string(self):
        d = cp._job_date_value("08/20/2017 - 08/22/2017")
        self.assertEqual(d, "2017-08-20")
        self.assertIsInstance(d, str)


class SheetClock(unittest.TestCase):
    # 00218: sheets on p80 (zones 1-3, Feb 9), p86 (1-5, Feb 28) and p97
    # (zone 19, Mar 4); the "Zone 19" chart is p98 (index 97)
    TIMES = {79: {1: {"start": "3:40"}, 2: {"start": "5:20"}},
             85: {1: {"start": "19:38"}, 5: {"start": "22:00"}},
             96: {19: {"start": "23:06", "stop": "1:36"}}}
    DATES = {79: "2017-02-09", 85: "2017-02-28", 96: "2017-03-04"}

    def test_the_zone_takes_the_sheet_in_front_of_it(self):
        self.assertEqual(cp.sheet_clock(self.TIMES, self.DATES, 97, 19),
                         ("23:06:00", "2017-03-04"))
        self.assertEqual(cp.sheet_clock(self.TIMES, self.DATES, 86, 1),
                         ("19:38:00", "2017-02-28"))
        self.assertEqual(cp.sheet_clock(self.TIMES, self.DATES, 80, 1),
                         ("03:40:00", "2017-02-09"))

    def test_a_zone_its_own_sheet_does_not_time_stays_blank(self):
        # 00226 p166: a second "Zone 15" behind a sheet for zones 16-20
        self.assertIsNone(cp.sheet_clock(self.TIMES, self.DATES, 97, 5))

    def test_no_sheet_before_the_chart_means_no_clock(self):
        self.assertIsNone(cp.sheet_clock(self.TIMES, self.DATES, 10, 1))


if __name__ == "__main__":
    unittest.main()
