"""Printed scales and wraps (wellsight_scales.py).

The scale blocks below are made up in the layout the drive's logs store
them in; the curves are made-up readings. The real log and printout run
when F2C_WS_SAMPLES names a folder holding 0229--10C057_LOG_HZ_Build.slg
and its .pdf.

Run: python3 -m unittest tests.test_wellsight_scales
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wellsight_scales as sc                                  # noqa: E402


def block(sections):
    """bytes of a scale block: [(depth, [left], [right])]"""
    b = struct.pack("<i", len(sections))
    for d, left, right in sections:
        n = len(left)
        b += struct.pack("<d", d) + struct.pack("<i", n) + struct.pack("<%dd" % n, *left)
        b += struct.pack("<i", n) + struct.pack("<%dd" % n, *right)
    return b


class Blocks(unittest.TestCase):
    def test_one_section(self):
        body = b"\x00" * 7 + block([(575.0, [0, 0, 0], [5, 1000, 150])]) + b"\x09\x00"
        p = 7 + 12                                    # the table, past the count and the depth
        tab = sc._table_at(body, p)
        self.assertEqual(tab[:3], (3, [0, 0, 0], [5, 1000, 150]))
        secs, end = sc._sections(body, p)
        self.assertEqual(secs, [(575.0, [0, 0, 0], [5, 1000, 150])])
        self.assertEqual(body[end:], b"\x09\x00")

    def test_a_scale_changing_down_the_log(self):
        body = block([(1130.0, [0, 0], [500, 150]), (1410.0, [0, 0], [4000, 150])])
        secs, _end = sc._sections(body, 12)
        self.assertEqual([s[0] for s in secs], [1130.0, 1410.0])
        self.assertEqual(sc.scale_at([(1130.0, 0, 500), (1410.0, 0, 4000)], 1409.9), (0, 500))
        self.assertEqual(sc.scale_at([(1130.0, 0, 500), (1410.0, 0, 4000)], 1410.0), (0, 4000))

    def test_not_a_table(self):
        self.assertIsNone(sc._table_at(struct.pack("<i", 2) + struct.pack("<2d", 0, 0) + struct.pack("<i", 3), 0))
        same = struct.pack("<i", 1) + struct.pack("<d", 5) + struct.pack("<i", 1) + struct.pack("<d", 5)
        self.assertIsNone(sc._table_at(same, 0))     # a scale of no width


class Printed(unittest.TestCase):
    def test_in_the_scale(self):
        self.assertEqual(sc.printed(500, 0, 1000), (0.5, 0))

    def test_past_it_once_and_twice(self):
        p, k = sc.printed(1037, 0, 1000)
        self.assertEqual(k, 1)
        self.assertAlmostEqual(p, 0.037)
        self.assertEqual(sc.printed(2500, 0, 1000)[1], 2)

    def test_the_right_value_itself_is_not_a_wrap(self):
        self.assertEqual(sc.printed(1000, 0, 1000), (1.0, 0))

    def test_a_reversed_scale(self):
        # ROP printed 20 to 0: 25 min/m is past the 20 end
        p, k = sc.printed(25, 20, 0)
        self.assertEqual(k, -1)
        self.assertAlmostEqual(p, 0.75)

    def test_no_reading(self):
        self.assertIsNone(sc.printed(None, 0, 10))
        self.assertIsNone(sc.printed(float("nan"), 0, 10))


class Wraps(unittest.TestCase):
    def curve(self, vals, d0=1000.0, step=0.5):
        return {"first_depth": d0, "step": step, "values": vals}

    def test_runs_of_wrapped_readings(self):
        c = self.curve([500, 1037, 1200, 900, 2500, 2600, 400, None, 1100])
        w = sc.wraps(c, [(1000.0, 0, 1000)])
        self.assertEqual([(x["top"], x["base"], x["wraps"], x["peak"]) for x in w],
                         [(1000.5, 1001.5, 1, 1200), (1002.0, 1003.0, 2, 2600), (1004.0, 1004.5, 1, 1100)])

    def test_a_new_scale_ends_the_wraps(self):
        c = self.curve([600, 700, 800, 900], step=1.0)
        w = sc.wraps(c, [(1000.0, 0, 500), (1002.0, 0, 4000)])
        self.assertEqual([(x["top"], x["base"]) for x in w], [(1000.0, 1002.0)])

    def test_reversed_scale_wraps_the_other_way(self):
        w = sc.wraps(self.curve([10, 25, 30, 5]), [(1000.0, 20, 0)])
        # 25 and 30 min/m are above the scale's high value (20), printed on its left side
        self.assertEqual([(x["wraps"], x["peak"]) for x in w], [(1, 30)])


class Drawing(unittest.TestCase):
    def test_the_two_lines(self):
        self.assertEqual(sc.drawn(400, 0, 1000), (0.4, 0.0))      # wrap line along the low end
        self.assertEqual(sc.drawn(1300, 0, 1000), (1.0, 0.3))     # main along the high end, wrap inside
        self.assertEqual(sc.drawn(2600, 0, 1000), (1.0, 1.0))     # past twice: both at the edge
        m, w = sc.drawn(25, 20, 0)                                # reversed: 20 is the high end
        self.assertAlmostEqual(m, 0.0)
        self.assertAlmostEqual(w, 0.75)

    def series(self, vals, left, right, gaps=()):
        """what a reader sees: the main line inside the track and the wrap
        line, except where a dash leaves a gap; the main line is not drawn
        along the high end (LogViewer leaves it off once the wrap takes over)"""
        out = []
        for i, v in enumerate(vals):
            if i in gaps:
                out.append([])
                continue
            m, w = sc.drawn(v, left, right)
            hi_end = 1.0 if right > left else 0.0
            out.append([p for p in (m, w) if not (p == hi_end and p == m and w != (1 - hi_end))])
        return out

    def test_reading_a_wrapped_curve_back(self):
        vals = [300, 600, 950, 1037, 1300, 1450, 1100, 980, 700, 400]
        got = sc.read_drawn(self.series(vals, 0, 1000, gaps=(5,)), 0, 1000)
        for v, g in zip(vals, got):
            if g is None:
                continue
            self.assertTrue(g[1])
            self.assertAlmostEqual(g[0], v, places=6)
        self.assertIsNone(got[5])                                  # the dash's gap

    def test_a_reversed_scale_read_back(self):
        vals = [5, 12, 19, 26, 31, 22, 15]
        got = sc.read_drawn(self.series(vals, 20, 0), 20, 0)
        self.assertEqual([round(g[0], 6) for g in got], vals)

    def test_past_twice_the_scale_is_a_bound(self):
        got = sc.read_drawn([[0.9, 0.0], [1.0, 1.0]], 0, 1000)
        self.assertEqual(got[1], (2000.0, False))


SAMPLES = os.environ.get("F2C_WS_SAMPLES") or ""
LOG = os.path.join(SAMPLES, "0229--10C057_LOG_HZ_Build.slg")


@unittest.skipUnless(os.path.exists(LOG), "set F2C_WS_SAMPLES to the folder with the 0229 sample log")
class RealLog(unittest.TestCase):
    def test_the_printed_scales(self):
        import wellsight_app as wa
        raw = open(LOG, "rb").read()
        log = wa.ws.read_log(raw)
        s = sc.scales(raw, log["curves"])
        got = {log["curves"][i]["name"]: v for i, v in s.items() if log["curves"][i]["nonnull"]}
        # as the printout's curve header prints them
        self.assertEqual(got, {"ROP": [(575.0, 0.0, 5.0)], "Pason Gas": [(575.0, 0.0, 1000.0)],
                               "Gamma": [(575.0, 0.0, 150.0)]})

    @unittest.skipUnless(os.path.exists(LOG[:-4] + ".pdf"), "no printout beside the sample log")
    def test_gas_read_back_off_the_printout(self):
        import fitz
        import wellsight_app as wa
        import wellsight_print as wp
        raw = open(LOG, "rb").read()
        log = wa.ws.read_log(raw)
        strip, info = wp.stitch(LOG[:-4] + ".pdf", log["top"], log["bottom"])
        pg = fitz.open(stream=strip, filetype="pdf")[0]
        c0, c1 = info["curves_pt"]
        red = [(it[1], it[2]) for d in pg.get_drawings() if d.get("color") and
               tuple(round(v, 2) for v in d["color"]) == (1.0, 0.0, 0.0)
               for it in d["items"] if it[0] == "l"]
        gas = next(c for c in log["curves"] if c["name"] == "Pason Gas")
        series = []
        for k in range(len(gas["values"])):
            y = (gas["first_depth"] + (k - 0.5) * gas["step"] - log["top"]) * info["pt_per_m"]
            xs = []
            for a, b in red:
                y0, y1 = sorted((a.y, b.y))
                if y0 - 0.6 <= y <= y1 + 0.6:
                    yy = min(max(y, y0), y1)
                    xs.append(a.x if abs(b.y - a.y) < 1e-6 else a.x + (b.x - a.x) * (yy - a.y) / (b.y - a.y))
            series.append([(x - c0) / (c1 - c0) for x in xs])
        got = sc.read_drawn(series, 0, 1000)
        past = [(v, g) for v, g in zip(gas["values"], got) if v is not None and v > 1000 and g]
        right = sum(1 for v, g in past if g[1] and abs(g[0] - v) <= 20)
        self.assertGreaterEqual(len(past), 40)
        self.assertGreaterEqual(right / len(past), 0.85)      # wrapped readings read back off the drawing


if __name__ == "__main__":
    unittest.main()
