"""A BJ-1 title's description set off by a dash is kept in the stage key.

  python3 -m unittest tests.test_bj_stage_dash

bj1 keeps the description printed after a stage number — "- Stage 06 Plug
Slip" is stage "6 Plug Slip", not a second chart of stage 6 — so an aborted
run and the treatment after it stay two charts. 01251 prints the same thing
with a dash: "- Stage 04 - Plug Slip" and "- Stage 04 - Re-attempt". Neither
matched, both read as stage "4", and pipeline could only number them "4" and
"4 (2)" with a note that nothing printed tells them apart, when the titles
do. The dashed form is read only where the plain one finds nothing, so no
title the plain form reads changes key.
"""
import datetime
import importlib.util
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import bj1                                               # noqa: E402

UWI = "103/02-26-080-17W6 - Well D"


class DashedDescription(unittest.TestCase):

    def key(self, tail, stage):
        return bj1._qualified_stage(f"{UWI} - Stage {tail}", stage)

    def test_the_titles_01251_01249_01253_00636_print(self):
        for tail, stage, want in (
                ("04 - Plug Slip", "4", "4 Plug Slip"),
                ("04 - Re-attempt", "4", "4 Re-attempt"),
                ("07 - Reattempt", "7", "7 Reattempt"),
                ("29 - First Attempt", "29", "29 First Attempt"),
                ("29 - Second Attempt", "29", "29 Second Attempt"),
                ("11 - Re-Attempt", "11", "11 Re-Attempt"),
                ("13 - 1st Re-Attempt", "13", "13 1st Re-Attempt"),
                ("13 - Second Re-Attempt", "13", "13 Second Re-Attempt"),
                ("05 - Gel Pill for Wireline", "5", "5 Gel Pill for Wireline")):
            self.assertEqual(self.key(tail, stage), want, tail)

    def test_the_dash_and_the_plain_form_name_one_run_alike(self):
        self.assertEqual(self.key("04 - Plug Slip", "4"),
                         self.key("04 Plug Slip", "4"))

    def test_an_en_or_em_dash_and_no_spaces(self):
        self.assertEqual(self.key("04 – Plug Slip", "4"), "4 Plug Slip")
        self.assertEqual(self.key("04 — Plug Slip", "4"), "4 Plug Slip")
        self.assertEqual(self.key("04-Plug Slip", "4"), "4 Plug Slip")

    def test_a_re_pump_number_keeps_its_point(self):
        self.assertEqual(self.key("10.1 - Plug Slip", "10"), "10.1 Plug Slip")

    def test_what_is_not_a_description_changes_nothing(self):
        for tail in ("10 - 2", "10 - ", "10 -", "10 - (A)", "10 - Plug/Slip",
                     "10 - a"):
            self.assertEqual(self.key(tail, "10"), "10", tail)

    def test_another_number_than_the_one_read_changes_nothing(self):
        self.assertEqual(self.key("04 - Plug Slip", "5"), "5")


class ThePlainFormIsUnchanged(unittest.TestCase):
    """Every title the plain pattern reads keeps the key it had."""

    def test_plain_titles(self):
        for tail, stage, want in (
                ("06", "6", "6"),
                ("06 Plug Slip", "6", "6 Plug Slip"),
                ("17 HRF", "17", "17 HRF"),
                ("41 Winterize", "41", "41 Winterize"),
                ("10.1", "10", "10.1"),
                ("36.2HRF", "36", "36.2 HRF"),
                ("23a", "23", "23 a"),
                ("03 Plug Wash", "3", "3 Plug Wash")):
            self.assertEqual(
                bj1._qualified_stage(f"{UWI} - Stage {tail}", stage), want, tail)

    def test_no_title(self):
        self.assertEqual(bj1._qualified_stage("", "4"), "4")
        self.assertEqual(bj1._qualified_stage("", "2 Ball Seat Attempt"),
                         "2 Ball Seat Attempt")


def _pages():
    spec = importlib.util.spec_from_file_location(
        "_bj_pages", os.path.join(_HERE, "test_bj_start_date.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._chart


class ThroughThePipeline(unittest.TestCase):
    def test_two_runs_of_one_stage_keep_their_printed_names(self):
        import fitz
        import pipeline
        chart = _pages()
        doc = fitz.open()
        for title, first in (
                (f"{UWI} - Stage 04 - Plug Slip", datetime.datetime(2025, 5, 7, 11, 0)),
                (f"{UWI} - Stage 04 - Re-attempt", datetime.datetime(2025, 5, 7, 15, 45))):
            doc.insert_pdf(chart(first, 3, title=title))
        res, notes = pipeline.extract_document(
            doc, sample_sec=1.0, enable_raster=True,
            filename="01251-102022608017W600_49179_COMP_2025JUL26.PDF")
        stages = [r["meta"]["stage"] for r in res if r.get("type") == "series"]
        self.assertEqual(stages, ["4 Plug Slip", "4 Re-attempt"], notes)
        self.assertFalse(any("nothing printed to tell them apart" in n
                             for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
