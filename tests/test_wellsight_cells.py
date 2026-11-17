"""A WellSight log's Porosity and Grain Size cells as LAS curves
(wellsight_cells.py, and the LAS Save writes in wellsight_app.py).

The logs here are made up byte by byte the way the files store the cells, so
the right answers are known. The label spellings are ones the logs on the
WellSight drive use.

Run: python3 -m unittest tests.test_wellsight_cells
"""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import wellsight_cells as C                                    # noqa: E402
import wellsight_app as wa                                     # noqa: E402

POROSITY = ["24%", "18%", "12%", "6%"]            # 8 cells, 3 % each, the 0 % end last
GRADES = ["Excellent", "Good", "Fair", "Poor", "Very Poor"]
GRAIN = ["1/16 mm", "1/8 mm", "1/4 mm", "1/2 mm", "1 mm"]


def _s(t):
    t = t.encode("latin-1")
    return struct.pack("<I", len(t)) + t


def grid_bytes(title, labels, rows, step=0.5, k=None):
    """a cell column as the file stores it, after its graph-paper record (which
    also carries the title, followed by something that is not a grid)"""
    k = len(rows[0]) if rows else (k or len(labels))
    out = b"\x00" * 16 + _s(title) + struct.pack("<d", 0.4) + b"\x01\x01" + _s("Graph Paper") + b"\x00" * 8
    out += _s(title) + b"\x01" + struct.pack("<IIBI", k, 0, 1, len(labels))
    out += b"".join(_s(x) for x in labels)
    out += struct.pack("<I", 0x333333) + struct.pack("<d", step) + b"\x00" + struct.pack("<I", len(rows))
    for r in rows:
        out += struct.pack("<I", k) + bytes(r)
    return out + b"\x00" * 16


def read(body, titles=("Porosity", "Grain Size", "Grain/CrystalSize")):
    return C.grids(body, titles)


def curves(body, top, depths, step):
    cs, notes = C.las_curves(read(body), top, depths, step)
    return {mn: vals for mn, _, _, vals in cs}, notes


class Decode(unittest.TestCase):
    def test_a_porosity_grid_is_read_with_its_labels_and_rows(self):
        rows = [(0,) * 8, (0, 0, 0, 0, 0, 1, 1, 1), (0, 0, 0, 0, 1, 1, 1, 1)]
        g = read(grid_bytes("Porosity", POROSITY, rows))
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["kind"], g[0]["labels"], g[0]["step"], g[0]["rows"]),
                         ("porosity", POROSITY, 0.5, rows))

    def test_the_title_alone_is_not_a_grid(self):
        body = b"\x00" * 8 + _s("Porosity") + b"\x02" + b"\x00" * 40
        self.assertEqual(read(body), [])

    def test_a_column_of_another_name_is_not_looked_for(self):
        body = grid_bytes("Sorting", ["Well", "Moderate", "Poor"], [(1, 0, 0)])
        self.assertEqual(C.grids(body, ["Sorting"]), [])

    def test_both_grids_of_a_log(self):
        body = grid_bytes("Grain Size", GRAIN, [(1, 0, 0, 0, 0)]) + grid_bytes("Porosity", POROSITY, [(0,) * 7 + (1,)])
        self.assertEqual(sorted(g["kind"] for g in read(body)), ["grain", "porosity"])


class Porosity(unittest.TestCase):
    def test_a_bar_reads_as_the_porosity_where_it_ends(self):
        rows = [(0,) * 7 + (1,), (0,) * 5 + (1,) * 3, (0,) * 4 + (1,) * 4, (1,) * 8, (0,) * 8]
        got, notes = curves(grid_bytes("Porosity", POROSITY, rows, step=1.0), 1000.0,
                            [1000.0 + i for i in range(5)], 1.0)
        self.assertEqual(got["POR"], [3, 9, 12, 24, None])
        self.assertEqual(notes, [])

    def test_the_scale_however_it_is_labelled(self):
        for labels, k, scale in ((["24%", "18%", "12%", "6%"], 8, (7, 3.0)),
                                 (["24%", "21%", "18%", "15%", "12%", "9%", "6%", "3%"], 8, (7, 3.0)),
                                 (["21-24+", "18-21", "15-18", "12-15", "9-12", "6-9", "3-6", "0-3"], 8, (7, 3.0)),
                                 (["18%", "15%", "12%", "9%", "6%", "3%"], 6, (5, 3.0)),
                                 (["3%", "6%", "9%", "12%"], 4, (0, 3.0))):
            self.assertEqual(C.porosity_scale(labels, k), scale, labels)

    def test_labels_counting_up(self):
        got, _ = curves(grid_bytes("Porosity", ["3%", "6%", "9%", "12%"], [(1, 1, 0, 0)]), 1000.0, [1000.0], 0.5)
        self.assertEqual(got["POR"], [6])

    def test_grades_are_not_a_porosity_and_are_left_out(self):
        got, notes = curves(grid_bytes("Porosity", GRADES, [(0, 0, 0, 1, 1)]), 1000.0, [1000.0], 0.5)
        self.assertEqual(got, {})
        self.assertEqual(len(notes), 1)
        self.assertIn("grades", notes[0])

    def test_the_curve_is_in_percent(self):
        cs, _ = C.las_curves(read(grid_bytes("Porosity", POROSITY, [(0,) * 7 + (1,)])), 1000.0, [1000.0], 0.5)
        self.assertEqual([(mn, unit) for mn, unit, _, _ in cs], [("POR", "%")])
        self.assertIn("3 % a cell", cs[0][2])


class Grain(unittest.TestCase):
    def test_a_range_fills_each_of_its_cells(self):
        rows = [(0, 1, 1, 1, 0), (0, 0, 0, 0, 0), (1, 0, 0, 0, 0)]
        got, _ = curves(grid_bytes("Grain Size", GRAIN, rows), 1000.0, [1000.0, 1000.5, 1001.0], 0.5)
        self.assertEqual([got[mn][0] for mn, _, _ in C.GRAIN_CELLS], [0, 1, 1, 1, 0])
        self.assertEqual([got[mn][1] for mn, _, _ in C.GRAIN_CELLS], [None] * 5)
        self.assertEqual([got[mn][2] for mn, _, _ in C.GRAIN_CELLS], [1, 0, 0, 0, 0])

    def test_named_labels_go_on_the_standard_cells(self):
        for labels in (["vf", "f", "m", "c", "vc"], ["L-U vf", "L-U f", "L-U m", "L-U c", "L-U vc"],
                       ["Very Fine", "Fine", "Medium", "Coarse", "Very Coarse"],
                       ["v f gr", "f gr", "med gr", "c gr", "v c gr"], ["1/16mm", "1/8mm", "1/4mm", "1/2mm", "1mm"],
                       ["1 mm", "1/2 mm", "1/4 mm", "1/8 mm", "1/16 mm"][::-1]):
            got, _ = curves(grid_bytes("Grain Size", labels, [(0, 0, 1, 0, 0)]), 1000.0, [1000.0], 0.5)
            self.assertEqual(got["GS_1_4MM"], [1], labels)
            self.assertEqual(got["GS_1_16MM"], [0], labels)

    def test_two_cells_a_label(self):
        labels = ["L-U vf", "L-U f", "L-U m", "L-U c", "L-U vc"]
        got, notes = curves(grid_bytes("Grain Size", labels, [(0, 1, 1, 0, 0, 0, 0, 0, 0, 0)]), 1000.0, [1000.0], 0.5)
        self.assertEqual(notes, [])
        self.assertEqual([got[mn][0] for mn, _, _ in C.GRAIN_CELLS], [1, 1, 0, 0, 0])

    def test_more_spellings(self):
        for label, cell in (("fn", 1), ("vf snd", 0), ("m snd", 2), ("c slt", None), (">vc", None), ("crs", 3),
                            ("v fine", 0), ("v coarse", 4), ("pebble", None)):
            self.assertEqual(C.grain_cell(label), cell, label)

    def test_reversed_mm_labels(self):
        got, _ = curves(grid_bytes("Grain Size", GRAIN[::-1], [(1, 0, 0, 0, 0)]), 1000.0, [1000.0], 0.5)
        self.assertEqual(got["GS_1MM"], [1])
        self.assertEqual(got["GS_1_16MM"], [0])

    def test_a_row_finer_than_very_fine_is_described_but_on_no_standard_cell(self):
        labels = ["Micritic", "Micxl/Sltst", "Very Fine", "Fine", "Medium", "Coarse"]
        rows = [(1, 1, 0, 0, 0, 0), (1, 1, 1, 1, 0, 0)]
        got, _ = curves(grid_bytes("Grain Size", labels, rows), 1000.0, [1000.0, 1000.5], 0.5)
        self.assertEqual([got[mn][0] for mn, _, _ in C.GRAIN_CELLS], [0, 0, 0, 0, 0])
        self.assertEqual([got[mn][1] for mn, _, _ in C.GRAIN_CELLS], [1, 1, 0, 0, 0])

    def test_typos_on_the_drive(self):
        self.assertEqual(C.grain_cell("course"), 3)
        self.assertEqual(C.grain_cell("ver fine"), 0)
        self.assertEqual(C.grain_cell("> 1mm"), 4)
        self.assertIsNone(C.grain_cell("2 mm"))
        self.assertIsNone(C.grain_cell("silt"))

    def test_more_labels_than_cells_leaves_the_column_out(self):
        labels = ["Micritic", "Micxl/Sltst", "Very Fine", "Fine", "Medium", "Coarse"]
        got, notes = curves(grid_bytes("Grain Size", labels, [(1, 1, 1, 0, 0)]), 1000.0, [1000.0], 0.5)
        self.assertEqual(got, {})
        self.assertIn("6 labels for 5 cells", notes[0])

    def test_a_column_left_blank_adds_nothing(self):
        got, notes = curves(grid_bytes("Grain Size", GRAIN, [(0,) * 5] * 4), 1000.0, [1000.0], 0.5)
        self.assertEqual((got, notes), ({}, []))

    def test_labels_that_spell_out_their_class(self):
        for labels in (["vf(1/16 mm)", "f(1/8 mm)", "m(1/4 mm)", "c(1/2 mm)", "vc(1 mm)"],
                       ["VERY FINE 1/16-1/8 mm", "FINE 1/18-1/4 mm", "MEDIUM 1/4-1/2 mm", "COARSE 1/2-1 mm",
                        "VERY COARSE 1-2mm"],
                       ["v f sd", "f sd", "m sd", "c sd", "vc sd"]):
            got, notes = curves(grid_bytes("Grain Size", labels, [(0, 1, 0, 0, 0)]), 1000.0, [1000.0], 0.5)
            self.assertEqual(notes, [], labels)
            self.assertEqual(got["GS_1_8MM"], [1], labels)
        self.assertIsNone(C.grain_cell("SILT <1/16 mm"))
        self.assertIsNone(C.grain_cell("slt"))
        with self.assertRaises(KeyError):
            C.grain_cell("boulders")


class Depths(unittest.TestCase):
    def test_a_row_repeats_on_a_finer_step(self):
        rows = [(0,) * 7 + (1,), (0,) * 5 + (1,) * 3]
        depths = [1000.0 + 0.2 * k for k in range(5)]          # 1000.0 .. 1000.8
        got, _ = curves(grid_bytes("Porosity", POROSITY, rows), 1000.0, depths, 0.2)
        self.assertEqual(got["POR"], [3, 3, 3, 9, 9])

    def test_rows_finer_than_the_step_are_joined(self):
        rows = [(0,) * 8, (0,) * 6 + (1, 1), (0,) * 7 + (1,), (0,) * 8]
        got, _ = curves(grid_bytes("Porosity", POROSITY, rows, step=0.1), 1000.0, [1000.0, 1000.2], 0.2)
        self.assertEqual(got["POR"], [6, 3])
        g, _ = curves(grid_bytes("Grain Size", GRAIN, [(1, 0, 0, 0, 0), (0, 0, 1, 0, 0)], step=0.1), 1000.0,
                      [1000.0], 0.2)
        self.assertEqual([g[mn][0] for mn, _, _ in C.GRAIN_CELLS], [1, 0, 1, 0, 0])

    def test_rows_past_the_grid_are_null(self):
        got, _ = curves(grid_bytes("Porosity", POROSITY, [(0,) * 7 + (1,)]), 1000.0, [999.0, 1000.0, 1001.0], 0.5)
        self.assertEqual(got["POR"], [None, 3, None])

    def test_span_of_the_filled_rows(self):
        rows = [(0,) * 8, (0,) * 7 + (1,), (0,) * 8, (0,) * 6 + (1, 1), (0,) * 8]
        self.assertEqual(C.span(read(grid_bytes("Porosity", POROSITY, rows)), 1000.0), (1000.5, 1002.0))


class SavedLas(unittest.TestCase):
    """wellsight_app writes the cells into the LAS Save writes"""

    def las(self, body, grid, cols):
        log = {"top": 1000.0, "columns": ["Porosity", "Grain Size"]}
        meta = [("GR", {"units": "API", "description": "Gamma"})]
        notes = ["Content: curve-track data only (no lithology, text or survey)."]
        return wa._with_cells(b"STRIP.LOG" + body, log, (grid, 0.5), cols, meta, notes)

    def test_cells_follow_the_curves(self):
        body = grid_bytes("Porosity", POROSITY, [(0,) * 7 + (1,), (0,) * 6 + (1, 1)])
        (grid, step), cols, meta, notes = self.las(body, [1000.0, 1000.5], [[50.0, 60.0]])
        self.assertEqual([mn for mn, _ in meta], ["GR", "POR"])
        self.assertEqual(meta[1][1]["units"], "%")
        self.assertEqual(cols, [[50.0, 60.0], [3, 6]])
        self.assertIn("Porosity / Grain Size cells", notes[0])
        self.assertTrue(any("POR" in x for x in notes[1:]))

    def test_the_depths_stretch_to_take_in_every_filled_row(self):
        rows = [(0,) * 5] * 2 + [(0, 0, 0, 0, 1)] * 6
        body = grid_bytes("Grain Size", GRAIN, rows)
        (grid, step), cols, meta, notes = self.las(body, [1001.0, 1001.5], [[50.0, 60.0]])
        self.assertEqual(grid, [1000.0 + 0.5 * k for k in range(2, 8)])
        self.assertEqual(cols[0], [50.0, 60.0, None, None, None, None])
        self.assertEqual(meta[-1][0], "GS_1MM")
        self.assertEqual(cols[-1], [1] * 6)
        self.assertEqual(cols[1], [0] * 6)

    def test_a_log_without_cells_is_left_as_it_was(self):
        grid, cols = [1000.0, 1000.5], [[50.0, 60.0]]
        notes = ["Content: curve-track data only (no lithology, text or survey)."]
        out = self.las(b"\x00" * 64, grid, cols)
        self.assertEqual(out, ((grid, 0.5), cols, [("GR", {"units": "API", "description": "Gamma"})], notes))

    def test_a_mnemonic_already_taken(self):
        body = grid_bytes("Porosity", POROSITY, [(0,) * 7 + (1,)])
        log = {"top": 1000.0, "columns": ["Porosity"]}
        meta = [("POR", {"units": "", "description": "a curve of that name"})]
        _, _, meta, _ = wa._with_cells(b"STRIP.LOG" + body, log, ([1000.0], 0.5), [[1.0]], meta, [])
        self.assertEqual([mn for mn, _ in meta], ["POR", "POR_2"])


if __name__ == "__main__":
    unittest.main()
