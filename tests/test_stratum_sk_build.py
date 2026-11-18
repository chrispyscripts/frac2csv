"""web/scripts/build_sk.py: placing a WellSight well and binning its log.

Synthetic headers, sections and logs only: the WellSight logs are not public,
so nothing here comes from them.
"""
import csv
import json
import math
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "web", "scripts"))
import build_sk as B  # noqa: E402

LAB = os.path.expanduser("~/dev/frac-wt/wellsight")
HAS_LAB = os.path.exists(os.path.join(LAB, "wellsight_symbols.py")) and os.path.exists(os.path.join(LAB, "log_vocab.py"))


def square_section(lat0=50.0, lon0=-104.0, m=1600.0):
    """a section m metres square with its SW corner at (lat0, lon0): (SW, SE, NW, NE) as (lon, lat)"""
    dlat, dlon = m / 111320, m / (111320 * math.cos(math.radians(lat0)))
    return ((lon0, lat0), (lon0 + dlon, lat0), (lon0, lat0 + dlat), (lon0 + dlon, lat0 + dlat))


def grid_of(sections):
    g = B.Sections("unused")
    for k, c in sections.items():
        g.corners[k] = c
        lon, lat = sum(q[0] for q in c) / 4, sum(q[1] for q in c) / 4
        g.cells[(int(lat // g.CELL), int(lon // g.CELL))].append(k)
    return g


class Locations(unittest.TestCase):
    def test_plain_and_prefixed(self):
        self.assertEqual(B.locations("7-14-21-11 W2M"), [("", (7, 14, 21, 11, 2))])
        self.assertEqual(B.locations("2B7-14-021-11W2"), [("", (7, 14, 21, 11, 2))])

    def test_a_uwi_names_the_bottom_hole(self):
        self.assertEqual(B.locations("191/07-14-021-11W2/00"), [("bh", (7, 14, 21, 11, 2))])

    def test_a_pair_is_surface_then_bottom_hole(self):
        self.assertEqual(B.locations("3A2-13/2B7-14-21-11W2"), [("surface", (2, 13, 21, 11, 2)), ("bh", (7, 14, 21, 11, 2))])

    def test_labelled(self):
        locs = B.locations("Surface: 5-9-33-18W3    BTM Hole: 12-4-33-18W3")
        self.assertEqual(locs, [("surface", (5, 9, 33, 18, 3)), ("bh", (12, 4, 33, 18, 3))])

    def test_in_words(self):
        self.assertEqual(B.locations("Lsd. 7, Sec. 14, Twp. 021, Rge. 11 W2M"), [("", (7, 14, 21, 11, 2))])

    def test_out_of_range_parts_are_not_locations(self):
        self.assertEqual(B.locations("17-14-21-11W2"), [])
        self.assertEqual(B.locations(""), [])


class Offsets(unittest.TestCase):
    def test_surface_from_edges(self):
        self.assertEqual(B.surface_offsets("123.40 m NORTH of SOUTH and 456.70 m EAST OF WEST Bdy of Section # 14"),
                         (("S", 123.4), ("W", 456.7), 14))
        self.assertEqual(B.surface_offsets("345.0m S of N & 75.0m W of E (2B7-14)"), (("N", 345.0), ("E", 75.0), 14))

    def test_surface_from_a_corner(self):
        # south and west from the north-east corner: from the north and east edges
        self.assertEqual(B.surface_offsets("120.5 m S; 80.25 m W; as measured from the NE corner of Sec. 9"),
                         (("N", 120.5), ("E", 80.25), 9))

    def test_surface_without_a_section(self):
        self.assertEqual(B.surface_offsets("85.00 m North of South  95.00 m East of West"), (("S", 85.0), ("W", 95.0), None))

    def test_a_typo_in_a_number_does_not_stop_it(self):
        self.assertIsNotNone(B.surface_offsets("210.0.0 m North of South, 85 m East of West, Sec 14"))

    def test_bottom_hole_from_the_well(self):
        self.assertEqual(B.bh_offsets("123.40 m NORTH and 1456.70 m EAST of surface location."), (123.4, 1456.7))
        self.assertEqual(B.bh_offsets("Referenced to well center:  1234.50 m South, 98.70 m West, 1238.40 m VS"), (-1234.5, -98.7))
        self.assertEqual(B.bh_offsets("From Well Centre: 876.50 m North, 432.10 m East."), (876.5, 432.1))

    def test_bottom_hole_after_the_casing_point(self):
        self.assertEqual(B.bh_offsets("ICP @ North 4.25m, East 210.50m of well centre. FTD@ North 9.8m, East 1488.4m of well centre."), (9.8, 1488.4))

    def test_bottom_hole_from_section_edges_is_not_an_offset(self):
        self.assertIsNone(B.bh_offsets("345m S of N Bdy, 210.5m E of W Bdy, Sec 23"))
        self.assertIsNone(B.bh_offsets("712.30 m N-S of Well Center 6.40 m E-W of Well Center"))


class Paths(unittest.TestCase):
    def test_straight_down(self):
        t = B.min_curvature([(0, 0, 0, 0), (1000, None, 0, 0)])
        self.assertAlmostEqual(t[-1][1], 1000, places=6)
        self.assertAlmostEqual(math.hypot(t[-1][2], t[-1][3]), 0, places=6)

    def test_a_quarter_circle_east(self):
        # 0 to 90 degrees over pi/2 * 500 m of hole: radius 500, ending 500 m down and 500 m east
        md = math.pi / 2 * 500
        t = B.min_curvature([(0, 0, 0, 90), (md, None, 90, 90)])
        self.assertAlmostEqual(t[-1][1], 500, places=3)
        self.assertAlmostEqual(t[-1][3], 500, places=3)
        self.assertAlmostEqual(t[-1][2], 0, places=3)

    def test_md_and_tvd_head_for_the_bottom_hole(self):
        # down 1000 m, an arc to level, then 1000 m level heading north-east
        r = 300.0
        pts = [(1000 + math.pi / 2 * r, 1000 + r), (2000 + math.pi / 2 * r, 1000 + r)]
        t = B.md_tvd_path(pts, 45.0)
        md, tvd, ns, ew, inc, az = t[-1]
        self.assertAlmostEqual(tvd, 1000 + r, places=6)
        self.assertAlmostEqual(ns, ew, places=6)
        # the lateral's own 1000 m plus the arc's run sideways
        self.assertAlmostEqual(math.hypot(ns, ew), 1000 + r, delta=5)
        self.assertTrue(all(b[0] > a[0] for a, b in zip(t, t[1:])), "MD only grows")

    def test_a_survey_that_starts_in_the_build_keeps_its_own_depths(self):
        # the first station is already at 60 degrees, 1500 m along the hole and 1300 m down:
        # the hole above it goes down and builds to it, it is not curved from the surface
        stations = [(1500, 1300, 60, 90), (1600, 1340, 75, 90), (1700, 1360, 88, 90), (2700, 1375, 90, 90)]
        t = B.min_curvature(stations)
        at = {round(x[0]): x for x in t}
        self.assertAlmostEqual(at[1500][1], 1300, places=6)
        self.assertAlmostEqual(at[2700][1], 1375, places=6, msg="each station's own TVD")
        self.assertTrue(all(b[1] >= a[1] - 1e-6 for a, b in zip(t, t[1:])), "down all the way to the lateral")
        self.assertGreater(at[2700][3], 1000, "the lateral runs east")
        self.assertAlmostEqual(at[2700][2], 0, delta=1)
        # straight down to 343 m, then an arc of 1105 m radius to 60 degrees: 552 m east at the
        # first station (curving from the surface would put it 716 m east)
        self.assertAlmostEqual(at[1500][3], 552, delta=3)

    def test_heel(self):
        traj = [(0, 0, 0, 0, 0, 0), (1000, 1000, 0, 0, 0, 0), (1500, 1300, 0, 400, 85, 90), (2500, 1305, 0, 1400, 90, 90)]
        self.assertEqual(B.heel_of(traj), 1500, "the station the hole levels out from (past 80 degrees)")


class Sections(unittest.TestCase):
    def setUp(self):
        self.g = grid_of({(1, 1, 1, 2): square_section(), (2, 1, 1, 2): square_section(lon0=-104.0 - 1600 / (111320 * math.cos(math.radians(50))))})

    def test_lsd_centres_run_east_to_west_then_back(self):
        sw = self.g.corners[(1, 1, 1, 2)][0]
        east = lambda lsd: self.g.place(1, 1, 1, 2, lsd=lsd)[1]
        north = lambda lsd: self.g.place(1, 1, 1, 2, lsd=lsd)[0]
        self.assertGreater(east(1), east(2))      # LSD 1 is the SE corner
        self.assertGreater(east(8), east(5))      # 5-8 run back west to east
        self.assertGreater(north(13), north(1))
        self.assertAlmostEqual(north(1), sw[1] + 200 / 111320, places=5)

    def test_offsets_and_the_lsd_they_fall_in(self):
        lat, lon = self.g.place(1, 1, 1, 2, ("S", 100), ("E", 100))
        sw, se = self.g.corners[(1, 1, 1, 2)][:2]
        self.assertAlmostEqual(lat, sw[1] + 100 / 111320, places=5)
        self.assertLess(lon, se[0])
        self.assertEqual(self.g.last_lsd, 1)
        self.g.place(1, 1, 1, 2, ("N", 100), ("W", 100))
        self.assertEqual(self.g.last_lsd, 13)

    def test_find_by_number_near_a_point(self):
        lat, lon = self.g.place(2, 1, 1, 2, lsd=6)
        self.assertEqual(self.g.find(lat, lon), (2, 1, 1, 2))
        self.assertEqual(self.g.find(lat, lon, sec=1), (1, 1, 1, 2))
        self.assertIsNone(self.g.find(lat, lon, sec=7))

    def test_place_surface_from_its_coordinates(self):
        h = {"location": "191/06-02-001-01W2/00", "surface_coordinates": "100 m North of South, 100 m East of West, Sec 1"}
        got = B.place_surface(h, "", self.g, bh_off=(0, -1600))
        self.assertIsNotNone(got)
        lat, lon, key, how = got
        self.assertEqual(key[:4], (1, 1, 1, 2))
        self.assertIn("surface coordinates", how)


class StatedDepths(unittest.TestCase):
    def test_offsets_beside_a_stated_point(self):
        self.assertEqual(B.text_coords("TOE TOTAL DEPTH: 1520.0 m MD // 812.5 m TVD | TOE COORDINATES: 12.5 m S;  905.5 m E;"), (-12.5, 905.5))
        self.assertEqual(B.text_coords("Final Coordinates: 1104.5 m N; 8.5 m E"), (1104.5, 8.5))

    def test_a_minus_before_a_direction_is_the_direction(self):
        self.assertEqual(B.text_coords("ICP: 905.0 m MD, 742.5m TVD, -55.5 m SS, -95.5 m South, -210.5 m West"), (-95.5, -210.5))

    def test_offsets_from_a_section_corner_are_passed_over(self):
        t = "Coordinates: 410.5m S ; 285.5m W ; NE corner of Sec 14-21-11W2; 188.5m S & 4.5m W of well centre"
        self.assertEqual(B.text_coords(t), (-188.5, -4.5))
        self.assertIsNone(B.text_coords("375 m North of South Boundary, 60 m West of East Boundary"))
        self.assertIsNone(B.text_coords("Coordinates: 410.5m S; 285.5m W; NE corner of Sec 14-21-11W2"))
        self.assertIsNone(B.text_coords("SAND TOP @ 865.5 m MD // 801.5 m TVD (-12.5 m Subsea)"))

    def test_a_path_through_the_stated_points(self):
        # heel 850 m MD at 745 m TVD, 180 m east; toe 1390 m MD at 746 m TVD, 720 m east
        pts = [(800, 740, None, None), (850, 745, 0.0, 180.0), (1390, 746, 0.0, 720.0)]
        t = B.station_path(pts)
        end = t[-1]
        self.assertAlmostEqual(end[1], 746, places=6)
        self.assertAlmostEqual(end[3], 720, delta=1)
        self.assertAlmostEqual(end[2], 0, delta=1)
        heel = [x for x in t if abs(x[0] - 850) < 1e-6][0]
        self.assertAlmostEqual(heel[3], 180, delta=1)

    def test_an_offset_further_than_the_hole_ran_is_left_out(self):
        # 300 m of lateral cannot end 2 km away: the heading comes from the bottom hole instead
        pts = [(1000, 900, None, None), (1300, 905, 0.0, 2000.0)]
        t = B.station_path(pts, az=0.0)
        self.assertLess(abs(t[-1][3]), 50)
        self.assertGreater(t[-1][2], 100)

    def test_no_offsets_and_no_heading_is_no_path(self):
        self.assertIsNone(B.station_path([(1000, 900, None, None), (1300, 905, None, None)]))

    def test_mirrored_offsets_give_way_to_the_bottom_hole_location(self):
        pts = [(1000, 900, None, None), (1050, 905, 0.0, 200.0), (2400, 910, 0.0, 1500.0)]
        surface = (50.0, -104.0)
        k = math.cos(math.radians(50.0))
        west = (50.0, -104.0 - 1500 / (111320 * k))        # the bottom hole's own location is to the west
        t, how = B.stated_path(pts, None, surface, west)
        self.assertLess(t[-1][3], -1000)
        self.assertIn("toward the bottom hole location", how)
        east = (50.0, -104.0 + 1500 / (111320 * k))
        t, how = B.stated_path(pts, None, surface, east)
        self.assertGreater(t[-1][3], 1000)
        self.assertEqual(how, "the depths and offsets its log states")

    def test_nothing_to_point_it_by(self):
        self.assertEqual(B.stated_path([(1000, 900, None, None)], None, None, None)[0], None)


@unittest.skipUnless(HAS_LAB, "needs the frac2csv wellsight branch's modules")
class BinALog(unittest.TestCase):
    def test_stated_points_read_from_the_whole_annotation(self):
        B.use_lab(LAB)
        tail = " " * 130 + "TOE COORDINATES: 12.5 m S; 905.5 m E"
        pts = B.stated_points([{"annotations": [{"text": "TOE TOTAL DEPTH: 1520.0 m MD // 812.5 m TVD" + tail},
                                                {"text": "SAND TOP @ 865.5 m MD // 801.5 m TVD"}]}])
        self.assertEqual(pts, [(865.5, 801.5, None, None), (1520.0, 812.5, -12.5, 905.5)])

    def test_curves_rock_and_shows_on_md_bins(self):
        B.use_lab(LAB)
        with tempfile.TemporaryDirectory() as d:
            base = os.path.join(d, "HLG", "0001--synthetic.hl6")
            os.makedirs(os.path.dirname(base))
            json.dump({"curves": [{"mnemonic": "ROP", "name": "ROP"}, {"mnemonic": "GR", "name": "Gamma"}, {"mnemonic": "C", "name": "C 15"}],
                       "depth": {"log_top": 1000.0}, "columns": [], "header": {}, "lithology": {}}, open(base + ".json", "w"))
            with open(base + ".csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["DEPTH_M", "ROP [min/m]", "GR [API]", "C [ ]", "LITH"])
                for i in range(20):                      # 1000.0 .. 1009.5 every 0.5 m
                    w.writerow([1000 + i * .5, 2 + (i % 2), 80, 1, ""])
            with open(base + ".lithology.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["top_m", "base_m", "code", "rock", "symbol_id", "source"])
                w.writerow([1000, 1005, "SS", "Sandstone", 1, "x"])
                w.writerow([1005, 1010, "SH", "Shale", 2, "x"])
            with open(base + ".accessories.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["depth_m", "category", "code", "symbol_id", "size"])
                for dm in (1002.0, 1004.0, 1006.0):
                    w.writerow([dm, "Oil Show", "SPOTTED", 1, 0.04])
            res = B.bin_log((d, None, {"file": "HLG/0001--synthetic.hl6"}))
        bins = res["bins"]
        self.assertEqual(bins["c:rop"][500], 2.5, "the bin 1000-1002 m holds the mean of its readings")
        self.assertEqual(bins["gamma"][502], 80)
        self.assertFalse(any(k.startswith("x:c") for k in bins), "a placeholder track name is not a curve")
        self.assertEqual(bins["rock"][500], "sandstone")
        self.assertEqual(bins["rock"][503], "shale")
        self.assertIn(501, bins["show"])
        self.assertNotIn(499, bins["show"])


if __name__ == "__main__":
    unittest.main()
