"""web/scripts/build_viking.py and read_printouts.py: the Viking wells added to
FracView's Saskatchewan set from a Photon well export, the frac data and logs
read off printouts.

Every well, licence, location and number here is invented: the export, the
frac data and the printouts are not public.
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
import build_viking as V  # noqa: E402
import read_printouts as RP  # noqa: E402

LAB = os.path.expanduser("~/dev/frac-wt/wellsight")
HAS_LAB = os.path.exists(os.path.join(LAB, "log_vocab.py")) and os.path.exists(os.path.join(LAB, "wellsight_symbols.py"))

E0, N0 = 300000.0, 5650000.0            # an invented surface, NAD83 UTM 13


def pha_text(wells):
    """a small Photon export: the struct block, then each well and its sections"""
    head = ["# Photon Systems ASCII Format", "", "struct WELL {"] + ["    " + f for f in (
        "WELLID", "WELLNAME", "COMPANY", "LICENSE", "WELLSYMBOL", "TRAJECTORY", "FIELD", "POOL", "WELLFLUID",
        "FORMATION", "GRD", "KB", "TD", "TVD", "UTMZONE", "UTMX", "UTMY", "STATUS", "SPUDDATE", "SURFACE_UWI")] + ["}", ""]
    for name, fields in (("WELTOPS_MD", ("UNITS", "FMNDEPTH", "KEYNAME", "SNAME", "LNAME")),
                         ("DIR_XYZ", ("TYPE", "UNITS", "X", "Y", "Z", "INCL", "AZIM")),
                         ("STAGES", ("NUMBER", "LABEL", "TOP", "BOT", "TYPE", "DATE"))):
        head += ["struct %s[ N ] {" % name] + ["    " + f for f in fields] + ["}", ""]
    out = head
    for w in wells:
        out.append('WELL "%s"  "%s"  "Test Oil Ltd."  "%s" 0 "Horizontal"  "Testfield"  "Test Viking Sand Pool"  "Oil"  "Viking"  '
                   '650.0  654.0  %s  %s 13  %s  %s  "Active"  "2018-06-01"  "01-02-003-04W3"'
                   % (w["uwi"], w["name"], w["lic"], w["td"], w["tvd"], w.get("e", E0), w.get("n", N0)))
        if w.get("tops"):
            out.append("WELTOPS_MD  %d" % len(w["tops"]))
            out += ['"M"  %.2f  "%s"  "%s"  "%s"' % (d, t, t, t) for t, d in w["tops"]]
        if w.get("xyz"):
            out.append("DIR_XYZ %d" % len(w["xyz"]))
            out += ["0  m  %.2f  %.2f  %.2f  %.2f  %.2f" % r for r in w["xyz"]]
    return "\r\n".join(out) + "\r\n"


def lateral(r=300.0, n=40, reach=800.0):
    """straight down to 700 m, a quarter circle of radius r to horizontal,
    then east `reach` m: stations (x east, y north, z TVD, inc, az)"""
    st = [(0.0, 0.0, 0.0, 0.0, 90.0), (0.0, 0.0, 700.0, 0.0, 90.0)]
    for i in range(1, n + 1):
        a = math.pi / 2 * i / n
        st.append((r * (1 - math.cos(a)), 0.0, 700.0 + r * math.sin(a), math.degrees(a), 90.0))
    st.append((r + reach, 0.0, 700.0 + r, 90.0, 90.0))
    return st


def frac_csv(path, rows):
    head = ["UWI", "Stage", "COMPLTNxTOP", "START DATE", "START TIME", "END DATE", "END TIME", "BREAK DOWN", "ISIP",
            "MAX TREATING", "AVERAGE TREATING", "AVERAGE RATE", "FRAC GRADIENT", "FLUID PUMPED", "CO2 PUMPED",
            "N2 PUMPED", "PROP 1", "PROP 1 PUMPED", "PROP 1 PLACED", "PROP 2", "PROP 2 PUMPED", "PROP 2 PLACED"]
    units = ["", "", "M", "yyyy/mm/dd", "hh:mm", "yyyy/mm/dd", "hh:mm", "MPa", "MPa", "MPa", "MPa", "M3/MIN", "KPa/M",
             "M3", "M3", "SCM", "", "Tonne", "Tonne", "", "Tonne", "Tonne"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerow(units)
        for r in rows:
            w.writerow([r.get(h, "") for h in head])


class Names(unittest.TestCase):
    def test_licences_as_the_province_writes_them(self):
        self.assertEqual(V.lic_key("0999901"), "999901")
        self.assertEqual(V.lic_key("099Z901"), "99Z901")
        self.assertEqual(V.lic_key("009Z215"), "09Z215")
        self.assertEqual(V.lic_key("09Z215"), V.lic_key("009Z215"))

    def test_uwi(self):
        self.assertEqual(V.uwi_text("101011100109W400"), "101/01-11-001-09W4/00")
        self.assertEqual(V.uwi_key("101/01-11-001-09W4/00"), "101011100109W400")

    def test_printout_names(self):
        n = RP.parse_name("00012-101011100109W400._99Z001--SK0123456_LAT_LITH_LOG_20180601-WLS-Stitch.PDF")
        self.assertEqual((n["uwi"], n["licence"], n["maker"], n["stitched"]), ("101011100109W400", "99Z001", "WLS", True))
        n = RP.parse_name("00013-102011100109W400.__77777--SK0123457_LAT_LITH_LOG_20180602-TRI.PDF")
        self.assertEqual((n["licence"], n["maker"], n["stitched"]), ("77777", "TRI", False))
        self.assertIsNone(RP.parse_name("notes.pdf"))


class Geodesy(unittest.TestCase):
    def test_central_meridian_and_equator(self):
        lat, lon = V.utm_to_latlon(500000.0, 0.0, 13)
        self.assertAlmostEqual(lat, 0.0, places=9)
        self.assertAlmostEqual(lon, -105.0, places=9)

    def test_a_latitude_on_the_meridian(self):
        # the meridian's length to 50 N, integrated here (not Snyder's series)
        a, f = 6378137.0, 1 / 298.257222101
        e2 = f * (2 - f)
        n = 20000
        m = sum(a * (1 - e2) / (1 - e2 * math.sin((i + .5) * math.radians(50) / n) ** 2) ** 1.5 for i in range(n)) * math.radians(50) / n
        lat, lon = V.utm_to_latlon(500000.0, 0.9996 * m, 13)
        self.assertAlmostEqual(lat, 50.0, delta=1e-7)
        self.assertAlmostEqual(lon, -105.0, places=9)

    def test_east_and_west_mirror(self):
        a = V.utm_to_latlon(500000.0 + 150000, 5600000.0, 13)
        b = V.utm_to_latlon(500000.0 - 150000, 5600000.0, 13)
        self.assertAlmostEqual(a[0], b[0], places=9)
        self.assertAlmostEqual(a[1] + 105, -(b[1] + 105), places=9)


class Paths(unittest.TestCase):
    def test_arc_straight_is_the_chord(self):
        self.assertAlmostEqual(V.arc((0, 0, 0, 30, 45), (10, 10, 20, 30, 45)), math.dist((0, 0, 0), (10, 10, 20)))

    def test_arc_quarter_circle(self):
        r = 300.0
        self.assertAlmostEqual(V.arc((0, 0, 700, 0, 90), (r, 0, 700 + r, 90, 90)), math.pi * r / 2, places=6)

    def test_trajectory(self):
        w = {"UTMZONE": "13", "UTMX": str(E0), "UTMY": str(N0), "_sec": {"DIR_XYZ": [["0", "m"] + [str(v) for v in s] for s in lateral()]}}
        traj, lat0, lon0, lats, lons = V.pha_trajectory(w)
        md = [t[0] for t in traj]
        self.assertAlmostEqual(md[-1], 700 + math.pi * 300 / 2 + 800, delta=0.1)      # the bend's arc, not its chords
        self.assertAlmostEqual(traj[-1][1], 1000.0)                                     # TVD as given
        self.assertGreater(traj[-1][3], 1000)                                           # east
        self.assertLess(abs(traj[-1][2]), 60)                                           # UTM grid east is near true east here
        self.assertGreater(lons[-1], lon0)
        self.assertEqual(B.heel_of(traj) is not None, True)

    def test_no_survey(self):
        self.assertIsNone(V.pha_trajectory({"UTMX": str(E0), "UTMY": str(N0), "_sec": {}}))


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.pha = os.path.join(self.d, "test.pha")
        open(self.pha, "w").write(pha_text([
            {"uwi": "100010200304W300", "name": "TEST HZ A", "lic": "099Z001", "td": "1840.0", "tvd": "1000.0",
             "tops": [("COLORADO", 650.0), ("VIKING", 980.0)], "xyz": lateral()},
            {"uwi": "100020200304W300", "name": "TEST HZ B", "lic": "0777001", "td": "1840.0", "tvd": "1000.0",
             "e": E0 + 20, "xyz": lateral()},
            {"uwi": "100030200304W300", "name": "TEST HZ C", "lic": "0777002", "td": "1500.0", "tvd": "900.0"},
        ]))
        self.frac = os.path.join(self.d, "frac.csv")
        frac_csv(self.frac, [
            {"UWI": "100020200304W300", "Stage": "2", "COMPLTNxTOP": "1700", "START DATE": "2018/07/02", "START TIME": "9:00",
             "AVERAGE TREATING": "20.5", "MAX TREATING": "28.0", "AVERAGE RATE": "3.1", "FLUID PUMPED": "40.0",
             "PROP 1": "40/70 Sand", "PROP 1 PUMPED": "5.0", "PROP 1 PLACED": "4.5", "PROP 2": "20/40 Sand", "PROP 2 PUMPED": "2.0"},
            {"UWI": "100020200304W300", "Stage": "1", "COMPLTNxTOP": "1790", "START DATE": "2018/07/01", "ISIP": "7.0",
             "PROP 1": "40/70 Sand", "PROP 1 PUMPED": "6.0", "PROP 1 PLACED": "6.0"},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse(self):
        structs, wells = V.parse_pha(self.pha)
        self.assertEqual(len(wells), 3)
        self.assertEqual(structs["DIR_XYZ"], ["TYPE", "UNITS", "X", "Y", "Z", "INCL", "AZIM"])
        self.assertEqual(wells[0]["LICENSE"], "099Z001")
        self.assertEqual(len(wells[0]["_sec"]["DIR_XYZ"]), len(lateral()))
        self.assertEqual(wells[0]["_sec"]["WELTOPS_MD"][1][2], "VIKING")
        self.assertEqual(wells[2]["_sec"], {})

    def test_frac_stages(self):
        st, units = V.frac_stages(self.frac)
        s = st["100020200304W300"]
        self.assertEqual([x["n"] for x in s], [1, 2])                      # in stage order
        self.assertEqual(s[1]["date"], "2018-07-02")
        self.assertEqual(s[1]["proppant_t"], 6.5)                          # placed, else pumped
        self.assertEqual(s[1]["proppant_pumped_t"], 7.0)
        self.assertEqual(s[1]["avg_pressure_mpa"], 20.5)
        self.assertEqual(s[0]["isip_mpa"], 7.0)
        self.assertEqual(units["AVERAGE RATE"], "M3/MIN")
        self.assertEqual(V.depth_intervals(s)[0]["top_m"], 1790.0)

    def test_merge(self):
        # a WellSight well under the first licence, its path estimated
        old = {"key": "99Z001", "lat": 51.0, "lon": -108.0, "types": {"gamma": {"t": "Gamma ray", "u": "API"}}, "rock_names": {},
               "notes": [], "stages": [], "depth_intervals": [],
               "well": {"name": "OLD NAME", "licence": "99Z001", "path_estimated": True, "path_from": "the depths its log states",
                        "operator": "Test Oil Ltd.", "logs": 1},
               "trajectory": {"md": [0, 1000], "inc": [0, 0], "az": [0, 0], "tvd": [0, 1000], "ns": [0, 0], "ew": [0, 0],
                              "lat": [51.0, 51.0], "lon": [-108.0, -108.0]},
               "logs": {"bin": 2.0, "md0": 900.0, "n": 3, "types": {"gamma": [60, 70, 80]}, "src": [{"log": "horizontal"}]}}
        wells, skipped, rep = V.merge([old], {}, self.pha, self.frac)
        self.assertEqual(len(wells), 2)
        a = next(w for w in wells if w["key"] == "99Z001")
        self.assertIs(a, old)
        self.assertFalse(a["well"]["path_estimated"])
        self.assertEqual(a["well"]["path_from"], "survey (Photon export)")
        self.assertEqual(a["logs"]["types"]["gamma"], [60, 70, 80])           # its log kept
        self.assertGreater(len(a["trajectory"]["md"]), 2)
        self.assertEqual(a["well"]["tops"], [["COLORADO", 650.0], ["VIKING", 980.0]])
        b = next(w for w in wells if w["key"] == "777001")
        self.assertIsNone(b["logs"])
        self.assertEqual(b["well"]["uwi"], "100/02-02-003-04W3/00")
        self.assertEqual(len(b["stages"]), 2)
        self.assertEqual(len(b["depth_intervals"]), 2)
        self.assertEqual(rep["export wells added"], 1)
        self.assertEqual(skipped["Photon export: export wells with no survey"], 1)

    def test_written(self):
        wells, skipped, _ = V.merge([], {}, self.pha, self.frac)
        out = os.path.join(self.d, "out")
        B.write(out, wells, skipped, name="Saskatchewan", source="test")
        pads = json.load(open(os.path.join(out, "pads.json")))["pads"]
        self.assertEqual(len(pads), 1)                                       # 20 m apart: one pad
        ws = {w["wa"]: w for w in pads[0]["wells"]}
        self.assertEqual(ws["SK777001"]["stages"], 2)
        self.assertEqual(ws["SK777001"]["logs"], 0)
        index = json.load(open(os.path.join(out, "index.json")))
        self.assertEqual(index["name"], "Saskatchewan")
        self.assertEqual(index["pads"][0]["stages"], 2)
        self.assertEqual(index["pads"][0]["field"], "Test Viking Sand Pool")
        pad = json.load(open(os.path.join(out, "pads", pads[0]["id"] + ".json")))
        self.assertIsNone(next(w for w in pad["wells"] if w["well"]["wa"] == "SK777001")["logs"])


@unittest.skipUnless(HAS_LAB, "needs the frac2csv wellsight branch's modules")
class Printouts(unittest.TestCase):
    def test_attach(self):
        with tempfile.TemporaryDirectory() as d:
            json.dump({"ok": True, "file": "x.PDF", "licence": "777001", "maker": "WLS", "depth": {"top": 1000.0, "bottom": 1010.0},
                       "curves": [{"name": "Gamma", "kind": "gamma", "unit": "API", "top": 1000.0, "step": 1.0,
                                   "values": [50, 70, None, 90, 100, 110, None, None, 40, 60]}],
                       "rocks": [{"top": 1000.0, "base": 1004.0, "rock": "sandstone", "name": "Sandstone"},
                                 {"top": 1004.0, "base": 1010.0, "rock": "shale", "name": "Shale"}],
                       "shows": [{"depth": 1002.5, "term": "moderate"}, {"depth": 1003.0, "term": "trace"}, {"depth": 1006.0, "term": "dead"}],
                       "notes": ["a note"]}, open(os.path.join(d, "x.json"), "w"))
            has_log = {"key": "777001", "logs": {"types": {"gamma": [1]}}, "well": {}}
            new = {"key": "0777001", "logs": None, "well": {"logs": 0}}
            other = {"key": "888001", "logs": None, "well": {"logs": 0}}
            rep = {}
            from collections import Counter
            rep = Counter()
            RP.attach([has_log, new, other], d, rep)
            self.assertEqual(has_log["logs"], {"types": {"gamma": [1]}})        # a WellSight log stays
            self.assertIsNone(other["logs"])
            L = new["logs"]
            self.assertEqual(L["md0"], 1000.0)
            self.assertEqual(L["types"]["gamma"][0], 60.0)                       # bin 1000-1002: mean of 50, 70
            self.assertEqual(L["types"]["gamma"][1], 90.0)                       # 1002-1004: 1003 only (1002 empty)
            self.assertEqual(L["types"]["rock"][:3], ["sandstone", "sandstone", "shale"])
            self.assertEqual(L["types"]["show"][1], 3)                           # moderate, the strongest in the bin
            self.assertEqual(L["src"][0]["log"], "printout")
            self.assertEqual(new["well"]["log_from"], "printout")
            self.assertEqual(new["rock_names"]["shale"], "Shale")
            self.assertEqual(rep["wells given logs read off their printouts"], 1)

    def test_one_gamma_of_three(self):
        # a geosteering printout's Gamma, Gamma Up and Gamma Down (in CPS):
        # the plain Gamma, not the three averaged
        with tempfile.TemporaryDirectory() as d:
            cv = lambda name, unit, v: {"name": name, "kind": "gamma", "unit": unit, "top": 1000.0, "step": 1.0, "values": [v] * 4}
            json.dump({"ok": True, "file": "y.PDF", "licence": "777002", "maker": "GEO", "depth": {"top": 1000.0, "bottom": 1004.0},
                       "curves": [cv("Gamma Down", "CPS", 20.0), cv("Gamma", "API", 80.0), cv("Gamma Up", "API", 95.0)],
                       "rocks": [], "shows": [], "notes": []}, open(os.path.join(d, "y.json"), "w"))
            w = {"key": "777002", "logs": None, "well": {"logs": 0}}
            from collections import Counter
            RP.attach([w], d, Counter())
            self.assertEqual(w["logs"]["types"]["gamma"][0], 80.0)


class Compact(unittest.TestCase):
    """a pad file keeps a log's values to 4 figures and leaves empty fields out"""

    def test_sig(self):
        self.assertEqual(B.sig(11561.142), 11560)
        self.assertEqual(B.sig(104.07), 104.1)
        self.assertEqual(B.sig(0.0783456), 0.07835)
        self.assertEqual(B.sig(-36.934), -36.93)
        for v in (None, 0, 0.0, 7):
            self.assertEqual(B.sig(v), v)

    def test_compact_well(self):
        w = {"well": {"wa": "SK1"}, "trajectory": {"md": [0.0, 10.0]},
             "stages": [{"n": 1, "top_m": 1000.0, "isip_mpa": None, "proppants": []}],
             "depth_intervals": [{"n": 1, "top_m": 1000.0, "date": None}],
             "logs": {"bin": 2.0, "md0": 0.0, "n": 3, "src": [],
                      "types": {"gamma": [104.07, None, 98.123], "rock": [0, 2, None], "show": [None, 3, 3]}}}
        c = B.compact_well(w)
        self.assertEqual(c["stages"], [{"n": 1, "top_m": 1000.0, "proppants": []}])
        self.assertEqual(c["depth_intervals"], [{"n": 1, "top_m": 1000.0}])
        self.assertEqual(c["logs"]["types"], {"gamma": [104.1, None, 98.12], "rock": [0, 2, None], "show": [None, 3, 3]})
        self.assertEqual(w["logs"]["types"]["gamma"][0], 104.07)          # the well itself is left as it was
        self.assertIsNone(B.compact_well(dict(w, logs=None))["logs"])


if __name__ == "__main__":
    unittest.main()
