"""Where a WellSight log's tracks lie on its stitched printout
(wellsight_layout.py).

The layouts below are made up in the shape the drive's logs store them: a
strip log whose shown tracks run left to right after the curve track, with
hidden tracks and one whose record cannot be read whole; and a horizontal
log, whose pages are turned to stitch them, so its tracks run the other way
across the strip. Widths are in inches, printed at 72 pt to the inch.

Run: python3 -m unittest tests.test_wellsight_layout
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wellsight_layout as wl                                  # noqa: E402


def T(title, w, shown=True, cols=()):
    return {"title": title, "width_in": w, "shown": shown, "columns": list(cols)}


STRIP = [T("Curve Track 1", 2.3, cols=["Eng. Data"]), T("Depth", 0.16, cols=["Depth", "Events"]),
         T("% Lithology", 0.6, False, ["Fossil", "Mineral"]), T("Slide", 0.11),
         T("Porosity Type", 0.11, cols=["Porosity Type"]), T("Porosity", 0.4),
         T("", None, None, ["Fossil", "Mineral", "Stringer", "Texture"]),      # unreadable record
         T("Grain Size", 0.4), T("Sorting", 0.11, False, ["Sorting"]),
         T("Rounding", 0.11, False, ["Rounding"]), T("Oil Shows", 0.11, cols=["Oil Shows"]),
         T("Geological Descriptions", 3.45, cols=["Geol. Descrs."]), T("TG, C1-C5", 2.3, False)]
STRIP_LINES = [31.0, 196.5, 208.0, 216.0, 224.0, 252.5, 296.0, 324.5, 332.5, 581.0]

HORIZ = [T("Data Curves", 1.44, cols=["Eng. Data"]), T("Slide/Rotate", 0.07),
         T("Depth", 0.16, cols=["Depth", "Events"]),
         T("", None, None, ["Fossil", "Mineral", "Stringer", "Texture", "Geol. Descrs."]),
         T("Photos", 2.0, False), T("Oil Shows", 0.12, cols=["Oil Shows"]), T("Porosity", 0.48),
         T("% Lithology", 0.6, False), T("Porosity Type", 0.12, cols=["Porosity Type"]),
         T("Grain Size", 0.4), T("Rounding", 0.12, False), T("Sorting", 0.12, False),
         T("TG, C1-C5", 1.44, False)]
HORIZ_LINES = [0.5, 29.5, 38.0, 72.5, 81.0, 415.5, 427.0, 432.0, 535.5]


def spans(placed):
    return [(t["title"], t["x0"], t["x1"]) for t in placed]


class Place(unittest.TestCase):
    def test_strip_log_left_to_right(self):
        p = wl.place(STRIP, STRIP_LINES, (31.0, 196.5), 581.0, "Curve Track 1")
        self.assertEqual(spans(p), [
            ("Curve Track 1", 31.0, 196.5), ("Depth", 196.5, 208.0), ("Slide", 208.0, 216.0),
            ("Porosity Type", 216.0, 224.0), ("Porosity", 224.0, 252.5), ("Lithology", 252.5, 296.0),
            ("Grain Size", 296.0, 324.5), ("Oil Shows", 324.5, 332.5),
            ("Geological Descriptions", 332.5, 581.0)])
        self.assertTrue(all(t["snapped"] for t in p))

    def test_hidden_tracks_take_no_room(self):
        p = wl.place(STRIP, STRIP_LINES, (31.0, 196.5), 581.0, "Curve Track 1")
        titles = [t["title"] for t in p]
        for hidden in ("% Lithology", "Sorting", "Rounding", "TG, C1-C5"):
            self.assertNotIn(hidden, titles)

    def test_horizontal_log_runs_the_other_way(self):
        p = wl.place(HORIZ, HORIZ_LINES, (432.0, 535.5), 573.7, "Data Curves")
        self.assertEqual(spans(p), [
            ("Grain Size", 0.5, 29.5), ("Porosity Type", 29.5, 38.0), ("Porosity", 38.0, 72.5),
            ("Oil Shows", 72.5, 81.0), ("Lithology and descriptions", 81.0, 415.5),
            ("Depth", 415.5, 427.0), ("Slide/Rotate", 427.0, 432.0), ("Data Curves", 432.0, 535.5)])

    def test_curve_track_found_by_width_when_its_title_is_not_known(self):
        p = wl.place(STRIP, STRIP_LINES, (31.0, 196.5), 581.0, None)
        self.assertEqual(p[0]["title"], "Curve Track 1")
        self.assertIn("curves", p[0]["keys"])

    def test_tracks_past_the_page_edge_are_left_out(self):
        lines = [v for v in STRIP_LINES if v <= 332.5]
        p = wl.place(STRIP, lines, (31.0, 196.5), 400.0, "Curve Track 1")
        last = p[-1]
        self.assertEqual((last["title"], last["x1"]), ("Geological Descriptions", 400.0))
        self.assertTrue(last["clipped"])

    def test_an_edge_off_its_line_is_estimated_and_said_so(self):
        lines = [v for v in STRIP_LINES if v != 216.0]
        p = wl.place(STRIP, lines, (31.0, 196.5), 581.0, "Curve Track 1")
        slide = next(t for t in p if t["title"] == "Slide")
        self.assertFalse(slide["snapped"])
        self.assertAlmostEqual(slide["x1"], 216.0, delta=0.5)

    def test_nothing_without_a_curve_track(self):
        self.assertEqual(wl.place(STRIP, STRIP_LINES, None, 581.0, "Curve Track 1"), [])


class Keys(unittest.TestCase):
    def test_data_sets_by_column(self):
        p = {t["title"]: t["keys"] for t in wl.place(STRIP, STRIP_LINES, (31.0, 196.5), 581.0, "Curve Track 1")}
        self.assertIn("show", p["Oil Shows"])
        self.assertIn("porosity", p["Porosity Type"])
        self.assertIn("descriptions", p["Geological Descriptions"])
        self.assertTrue({"rock", "mineral", "fossil"} <= set(p["Lithology"]))
        self.assertTrue({"depth", "interval", "event"} <= set(p["Depth"]))
        self.assertIn("directional", p["Slide"])
        self.assertTrue({"curves", "eng"} <= set(p["Curve Track 1"]))

    def test_percent_lithology_is_its_own(self):
        self.assertEqual(wl.keys_of(T("% Lithology", 0.6)), ["pct"])


DRIVE = "/Volumes/CnC-2TB-ssd/SK-VIKING/WellSight/s-h-sl"
SAMPLES = os.environ.get("F2C_WS_SAMPLES") or DRIVE


def pairs(n=6):
    out = []
    for log in sorted(glob.glob(os.path.join(SAMPLES, "**", "*.*"), recursive=True)):
        if os.path.splitext(log)[1].lower() in (".sl6", ".slg", ".hl6", ".hlg"):
            pdf = os.path.splitext(log)[0] + ".pdf"
            if os.path.exists(pdf):
                out.append((log, pdf))
        if len(out) >= n:
            break
    return out


@unittest.skipUnless(pairs(), "no WellSight logs with their printouts on this machine")
class RealPrintouts(unittest.TestCase):
    def test_every_shown_track_lands_on_the_printout(self):
        import wellsight_app as wa
        import wellsight_print as wp
        for log, pdf in pairs():
            raw = open(log, "rb").read()
            p = wa.read(raw, os.path.basename(log))["payload"]
            _strip, info = wp.stitch(pdf, p["top"], p["bottom"])
            placed = wl.place(wl.read_tracks(raw), info["lines_pt"], info["curves_pt"],
                              info["width_pt"], wl.curve_track_title(p["curves"]))
            name = os.path.basename(log)
            self.assertTrue(placed, name)
            self.assertGreaterEqual(sum(t["snapped"] for t in placed), 0.8 * len(placed), name)


if __name__ == "__main__":
    unittest.main()
