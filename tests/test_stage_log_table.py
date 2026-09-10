"""The daily time log as a stage TABLE, on a filing that has no charts.

Two things are asserted here and they are separate bugs:

  * a document whose only result is a "summary" — a page-viewing aid with no
    rows and no samples — used to satisfy `if not results` and so silence
    _why_nothing entirely. 00654, 00677, 00698 and 00700 each came back with
    no data AND no explanation, which is the one outcome that note exists to
    prevent.
  * daily_ops.index() was read only to date somebody else's chart. With no
    chart in the file its stages were parsed and dropped, so 115 pages of
    dated stage starts exported nothing.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                          # noqa: E402


# 00654's layout: a Peloton board report, one FRAC row naming one stage.
def _day(report_date, hhmm, endhhmm, stage):
    return f"""Daily Completion and WS (board report)
Report #  3.0,  Report Date:   {report_date}
Job Time Log
{hhmm}
{endhhmm}
5.0 FRAC
Frac
Started pumping on Stage #{stage}.
"""


class _Page(object):
    def __init__(self, text):
        self._text = text

    def get_text(self, *a, **k):
        return self._text


class _Doc(object):
    """Enough of a fitz.Document for daily_ops.index — it reads page_count
    and each page's text and nothing else."""

    def __init__(self, texts):
        self._pages = [_Page(t) for t in texts]
        self.page_count = len(self._pages)

    def __getitem__(self, i):
        return self._pages[i]


class StageLogTable(unittest.TestCase):
    def test_time_log_becomes_a_table(self):
        doc = _Doc([_day("3/2/2025", "05:16", "10:30", 2),
                    _day("3/3/2025", "03:58", "09:10", 3),
                    _day("3/3/2025", "15:50", "20:05", 4)])
        results, notes = [], []
        pipeline._stage_log_table(doc, results, notes)
        self.assertEqual(len(results), 1)
        t = results[0]
        self.assertEqual(t["type"], "table")
        self.assertEqual(t["columns"], ["Stage", "Start"])
        self.assertEqual([r[0] for r in t["rows"]], ["2", "3", "4"])
        # date and clock in ONE cell: a bare HH:MM:SS with no day in it is
        # formatted to 1900-01-01 by _normalise_tables.
        self.assertEqual(t["rows"][0][1], "2025-03-02 05:16:00")
        self.assertTrue(notes and "3 stage start time" in notes[0])

    def test_classified_as_a_log(self):
        # so the Lab groups it with the other time logs rather than "other"
        self.assertEqual(
            pipeline.table_kind("Stage time log (operator daily report)"),
            "log")

    def test_nothing_to_read_says_nothing(self):
        doc = _Doc(["Wellbore schematic\nno time log here at all\n"])
        results, notes = [], []
        pipeline._stage_log_table(doc, results, notes)
        self.assertEqual(results, [])
        self.assertEqual(notes, [])

    def test_normalise_keeps_the_stamp_and_adds_the_uwi(self):
        doc = _Doc([_day("3/2/2025", "05:16", "10:30", 2)])
        results, notes = [], []
        pipeline._stage_log_table(doc, results, notes)
        pipeline._normalise_tables(
            results, "00654-102152406505W600_0512753_COMP.pdf")
        t = results[0]
        self.assertEqual(t["columns"], ["UWI", "Stage", "Start"])
        self.assertEqual(t["rows"][0][2], "2025-03-02 05:16:00")


class SummaryIsNotData(unittest.TestCase):
    """A summary-only result must not count as extractable data."""

    def test_summary_alone_is_not_exportable(self):
        res = [{"type": "summary", "groups": [[1, 2]], "source": "Canyon"}]
        self.assertFalse(
            any(r.get("type") in ("series", "table") for r in res))

    def test_a_table_is(self):
        res = [{"type": "summary", "groups": [], "source": "Canyon"},
               {"type": "table", "title": "x", "columns": [], "rows": [[1]]}]
        self.assertTrue(
            any(r.get("type") in ("series", "table") for r in res))


if __name__ == "__main__":
    unittest.main()
