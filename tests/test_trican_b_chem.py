"""A bad Chemical Summary page must not cost the file its stage table.

  python3 -m unittest tests.test_trican_b_chem

The layout-B book prints two tables: the per-stage pages (the primary source,
one row per stage) and a Chemical Summary (a second table, one row per stage,
one column per additive). A page that DETECTS as a chemical summary without
laying out like one returns nothing from _table_rows, which unpacked as
"not enough values to unpack (expected 2, got 0)" — and that exception left
parse_document entirely, so pipeline caught it and the file emitted no table
at all.

Measured on the first 91 files of a 419-file sweep: three files lost their
whole stage table this way — 00569 (102 stages), 00724 (51) and 00737 (51),
204 rows — every one of whose stage pages parsed perfectly.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import trican_b


class _Page:
    """Stands in for a page: detect_chem_summary is patched around it."""
    def __init__(self, tag): self.tag = tag


class _Doc:
    def __init__(self, pages): self._p = pages
    def __len__(self): return len(self._p)
    def __getitem__(self, i): return self._p[i]


class ChemSummaryIsNotWorthTheStageTable(unittest.TestCase):
    def setUp(self):
        self._detect = trican_b.detect_chem_summary
        self._rows = trican_b._table_rows
        trican_b.detect_chem_summary = lambda page: True

    def tearDown(self):
        trican_b.detect_chem_summary = self._detect
        trican_b._table_rows = self._rows

    def test_a_page_returning_nothing_does_not_raise(self):
        # the exact shape: _table_rows gives back an empty result
        trican_b._table_rows = lambda page, y_min=55.0: ()
        self.assertEqual(trican_b.parse_chem_summary(_Doc([_Page("a")])), {})

    def test_a_page_that_raises_does_not_raise(self):
        def boom(page, y_min=55.0): raise IndexError("ragged row")
        trican_b._table_rows = boom
        self.assertEqual(trican_b.parse_chem_summary(_Doc([_Page("a")])), {})

    def test_one_bad_page_does_not_lose_a_good_one(self):
        # the real files have several chemical-summary pages and only one is
        # unreadable — the others must still contribute
        def mixed(page, y_min=55.0):
            if page.tag == "bad":
                raise ValueError("not enough values to unpack")
            return ((0.0, 10.0), [["1", "2.5"]]), [["1", "2.5"]]
        trican_b._table_rows = mixed
        trican_b._head_names = lambda cols, heads: [None, "FR-9 (L)"]
        got = trican_b.parse_chem_summary(_Doc([_Page("bad"), _Page("ok")]))
        self.assertEqual(list(got), [1])
        self.assertTrue(any(k.startswith("chem_") for k in got[1]))

    def test_a_type_error_is_caught_too(self):
        def boom(page, y_min=55.0): return None
        trican_b._table_rows = boom
        self.assertEqual(trican_b.parse_chem_summary(_Doc([_Page("a")])), {})


if __name__ == "__main__":
    unittest.main()


class SummaryFillsGapsInTheStagePages(unittest.TestCase):
    """A stage the summary lists but no detail page covers must still appear.

    The consolidated Stage Summary was only ever used when there were NO
    per-stage pages at all. A file that ships both, and prints fewer detail
    pages than its own summary lists, silently lost the difference: 00720
    prints 48 stages in the summary and 46 per-stage pages, so stages 31 and
    39 vanished from a CSV whose report says 48.
    """

    def test_a_stage_only_the_summary_lists_is_kept(self):
        rows = [{"stage": 1, "depth_m": 1.5}, {"stage": 3}]
        printed = [{"stage": 1}, {"stage": 2}, {"stage": 3}]
        got = trican_b._merge_summary(rows, printed)
        self.assertEqual(sorted(r["stage"] for r in got), [1, 2, 3])

    def test_the_detail_page_wins_where_there_is_one(self):
        # the per-stage page carries a decimal more than the summary
        rows = [{"stage": 1, "depth_m": 1.55}]
        printed = [{"stage": 1, "depth_m": 2}]
        got = trican_b._merge_summary(rows, printed)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["depth_m"], 1.55)

    def test_nothing_missing_means_nothing_added(self):
        rows = [{"stage": 1}, {"stage": 2}]
        got = trican_b._merge_summary(rows, [{"stage": 1}, {"stage": 2}])
        self.assertEqual(len(got), 2)

    def test_an_empty_summary_changes_nothing(self):
        rows = [{"stage": 1}]
        self.assertEqual(trican_b._merge_summary(rows, []), rows)

    def test_the_00720_shape(self):
        # 46 detail pages, 48 printed, the two gaps at 31 and 39
        printed = [{"stage": n} for n in list(range(1, 32)) + list(range(39, 56))]
        rows = [{"stage": n} for n in [x["stage"] for x in printed
                                       if x["stage"] not in (31, 39)]]
        got = trican_b._merge_summary(rows, printed)
        self.assertEqual(len(got), len(printed))
        self.assertEqual(sorted(r["stage"] for r in got),
                         sorted(x["stage"] for x in printed))
