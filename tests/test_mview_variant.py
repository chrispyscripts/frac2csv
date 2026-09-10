"""Which MView sheet a page is, and what survives when the pair collapses.

Calfrac prints each zone twice — a "… Surface" sheet and a "… Bottom Hole"
sheet — and both carry Treating Pressure with different values. The tag is
what keeps them under separate keys; without it they share one key and that
channel ends up holding two recordings (#341).

Reading only the FIRST line was the same fault calfrac_progress.is_chart_page
had. A portrait MView sheet rotates the plot and OCR reads the y-axis tick
ladder before the caption, so page 73 of 00340 leads with "1400" and BOTH
sheets of every zone in the eight rotated filings came back untagged — the
#341 collision, in the files that had just been recovered from yielding
nothing at all.

And only ONE of the two sheets prints a date. When the Bottom Hole sheet won
the choice the stage lost its date on the way out: 17 of 52 charts dated on
00339, 22 of 52 on 00342.

Run: python3 -m unittest discover tests -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline                                          # noqa: E402


class _Page(object):
    pass


class Variant(unittest.TestCase):
    def setUp(self):
        self._real = pipeline.ocr_labels.page_text

    def tearDown(self):
        pipeline.ocr_labels.page_text = self._real

    def _tag(self, text):
        pipeline.ocr_labels.page_text = lambda page: text
        return pipeline._mview_variant(_Page())

    def test_landscape_title_on_the_first_line(self):
        self.assertEqual(self._tag(
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Surface\n"),
            " Surface")
        self.assertEqual(self._tag(
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Bottom Hole\n"),
            " BH")

    def test_rotated_sheet_leads_with_the_axis_ladder(self):
        # 00340 p73 and p74
        self.assertEqual(self._tag(
            "1400\n1000\n"
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Surface\n"
            "Zone: 1/85\n"), " Surface")
        self.assertEqual(self._tag(
            "1400\n1000\n"
            "Arc Hz Anten (Surf: 02-02) 100/04-10-066-25W5M Bottom Hole\n"
            "Zone: 1/85\n"), " BH")

    def test_the_chemicals_sheet_is_neither(self):
        self.assertEqual(self._tag(
            "1400\nArc Hz 100/04-10-066-25W5M Chemicals\n"), "")

    def test_a_later_line_must_look_like_a_title(self):
        # the word alone, with no well named, is a column heading — the same
        # thing is_chart_page refuses
        self.assertEqual(self._tag("Treatment Summary\nZone\nSurface\n"), "")

    def test_an_unreadable_page_is_untagged_not_an_error(self):
        def boom(page):
            raise RuntimeError("no")
        pipeline.ocr_labels.page_text = boom
        self.assertEqual(pipeline._mview_variant(_Page()), "")


def _chart(stage, data, date="", start=""):
    return {"type": "series", "source": "CalFrac chart",
            "data": {k: [1.0] for k in data},
            "meta": {"stage": stage, "date": date, "start_time": start}}


class Collapse(unittest.TestCase):
    """_pick_variant keeps one sheet per zone. What it keeps must not be
    poorer than what it dropped."""

    def test_surface_wins_when_it_carries_all_four(self):
        res = [_chart("1 Surface", pipeline._CANON4),
               _chart("1 BH", ("Tr Press",))]
        notes = []
        pipeline._pick_variant(res, notes)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["stage"], "1")
        self.assertEqual(len(res[0]["data"]), 4)

    def test_bottom_hole_wins_when_surface_is_short(self):
        res = [_chart("2 Surface", ("Tr Press", "Slurry Rate")),
               _chart("2 BH", pipeline._CANON4)]
        pipeline._pick_variant(res, [])
        self.assertEqual(len(res), 1)
        self.assertEqual(len(res[0]["data"]), 4)

    def test_the_date_is_carried_from_the_sheet_that_printed_it(self):
        # the Bottom Hole sheet prints no date and here it wins the choice
        res = [_chart("3 Surface", ("Tr Press",),
                      date="2022-03-01", start="04:12:00"),
               _chart("3 BH", pipeline._CANON4)]
        pipeline._pick_variant(res, [])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["date"], "2022-03-01")
        self.assertEqual(res[0]["meta"]["start_time"], "04:12:00")

    def test_the_kept_sheet_keeps_its_OWN_date(self):
        res = [_chart("4 Surface", pipeline._CANON4,
                      date="2022-03-02", start="09:00:00"),
               _chart("4 BH", ("Tr Press",),
                      date="1999-01-01", start="23:59:00")]
        pipeline._pick_variant(res, [])
        self.assertEqual(res[0]["meta"]["date"], "2022-03-02")
        self.assertEqual(res[0]["meta"]["start_time"], "09:00:00")

    def test_a_zone_with_one_sheet_is_untouched(self):
        res = [_chart("5 Surface", ("Tr Press",))]
        pipeline._pick_variant(res, [])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["meta"]["stage"], "5 Surface")


if __name__ == "__main__":
    unittest.main()
